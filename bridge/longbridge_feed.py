"""Longbridge OpenAPI quote push: broker-grade real-time trades, all US sessions.

Optional. Active only when credentials exist (runtime/longbridge.json or the
LONGBRIDGE_* environment variables); otherwise the Yahoo stream and HTTP polling
carry on unchanged. Unlike the Yahoo stream, Longbridge pushes name the trading
session, so a pushed trade may set the session label.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

SOURCE = '长桥实时推送'
SESSIONS = {'Pre': '盘前', 'Intraday': '盘中', 'Post': '盘后', 'Overnight': '夜盘'}
EXTENDED = {'Post', 'Overnight'}


def to_longbridge(symbol):
    """Yahoo-style code -> Longbridge code, or None when Longbridge has no such market."""
    if not isinstance(symbol, str): return None
    match = re.fullmatch(r'(\d{1,5})\.HK', symbol)
    if match: return str(int(match.group(1))) + '.HK'
    match = re.fullmatch(r'(\d{6})\.(SS|SZ)', symbol)
    if match: return match.group(1) + ('.SH' if match.group(2) == 'SS' else '.SZ')
    if re.fullmatch(r'[A-Z][A-Z0-9]{0,5}(-[A-Z])?', symbol): return symbol.replace('-', '.') + '.US'
    return None


def load_credentials(path, environ=os.environ):
    """App key, secret and access token from the JSON file, else the environment."""
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        data = {}
    keys = {'appKey': 'LONGBRIDGE_APP_KEY', 'appSecret': 'LONGBRIDGE_APP_SECRET', 'accessToken': 'LONGBRIDGE_ACCESS_TOKEN'}
    found = {name: str(data.get(name) or environ.get(env) or '').strip() for name, env in keys.items()}
    return found if all(found.values()) and not any(v.startswith('<') for v in found.values()) else None


def number(value):
    try:
        value = float(value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def epoch_of(stamp, now=None):
    """SDK datetimes may be naive; pick the reading that is not in the future."""
    now = now if now is not None else time.time()
    if not isinstance(stamp, datetime): return 0
    if stamp.tzinfo: return stamp.timestamp()
    readings = [stamp.replace(tzinfo=timezone.utc).timestamp(), stamp.timestamp()]
    plausible = [r for r in readings if r <= now + 60]
    return max(plausible) if plausible else 0


def auth_failure(exc):
    """401xxx: the credentials themselves are bad, not one symbol."""
    return str(getattr(exc, 'code', '') or '').startswith('401')


def describe(exc):
    if auth_failure(exc): return '失败：密钥无效或 Access Token 已过期，请在长桥开发者中心重新生成'
    text = str(exc).splitlines()[0][:120] if str(exc) else ''
    return '失败：' + text if text else '失败'


def session_name(value):
    return str(value).rsplit('.', 1)[-1]


def pushed(symbol, price, session, stamp, base, now=None):
    """One Longbridge trade -> the stream quote shape merge() understands.

    Pre-market and regular trades compare with the previous close; post-market and
    overnight with the regular close, matching how the HTTP sources label them.
    """
    price = number(price)
    name = session_name(session)
    if not price or name not in SESSIONS: return None
    reference = base.get('close') if name in EXTENDED else base.get('prev')
    if not reference: return None
    change = round(price - reference, 6)
    return {'symbol': symbol, 'price': price, 'change': change,
            'changePercent': round((price / reference - 1) * 100, 4),
            'epoch': epoch_of(stamp, now), 'currency': '', 'exchange': '',
            'session': SESSIONS[name], 'source': SOURCE}


def latest(quote, symbol, base, now=None):
    """Newest trade in a pulled SecurityQuote, across regular and extended sessions."""
    rows = [('Intraday', quote.last_done, quote.timestamp)]
    for name, attr in [('Pre', 'pre_market_quote'), ('Post', 'post_market_quote'), ('Overnight', 'overnight_quote')]:
        extra = getattr(quote, attr, None)
        if extra is not None: rows.append((name, extra.last_done, extra.timestamp))
    rows = [(epoch_of(t, now), n, p) for n, p, t in rows if number(p)]
    if not rows: return None
    stamp, name, price = max(rows, key=lambda r: r[0])
    result = pushed(symbol, price, name, None, base, now)
    if result: result['epoch'] = stamp
    return result


class LongbridgeFeed:
    """Owns one QuoteContext. Never raises into the worker; status explains failures."""

    def __init__(self, on_quote, credentials, log=print):
        self.on_quote = on_quote
        self.credentials = credentials
        self.log = log
        self.status = '连接中'
        self.running = False
        self.wanted = []
        self.live = set()
        self._names = {}
        self._base = {}
        self._lock = threading.Lock()
        self._thread = None

    def covers(self, symbol):
        return self.status == '已连接' and symbol in self.live

    def start(self, symbols=()):
        self.wanted = list(dict.fromkeys(symbols))
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def subscribe(self, symbols):
        self.wanted = list(dict.fromkeys(symbols))

    def stop(self):
        self.running = False

    def _on_push(self, code, event):
        with self._lock:
            symbol = self._names.get(code)
            base = self._base.get(code)
            if symbol is None or base is None: return
            quote = pushed(symbol, event.last_done, event.trade_session, event.timestamp, base)
            if quote and quote['session'] == '盘中': base['close'] = quote['price']
        if quote:
            try: self.on_quote(quote)
            except Exception: pass

    def _connect(self):
        from longbridge.openapi import Config, QuoteContext
        c = self.credentials
        config = Config.from_apikey(c['appKey'], c['appSecret'], c['accessToken'],
                                    enable_overnight=True, enable_print_quote_packages=False)
        context = QuoteContext(config)
        context.set_on_quote(self._on_push)
        return context

    def _sync(self, context, active, refused):
        """Match subscriptions to the wanted symbols. A code Longbridge refuses is
        remembered and left to the other sources rather than retried every loop."""
        from longbridge.openapi import SubType
        wanted = {to_longbridge(s): s for s in self.wanted if to_longbridge(s)}
        gone = [code for code in active if code not in wanted]
        if gone:
            context.unsubscribe(gone, [SubType.Quote])
            for code in gone: active.discard(code)
        for code in [c for c in wanted if c not in active and c not in refused]:
            try:
                quotes = [q for q in context.quote([code]) if q.symbol == code]
                if not quotes: raise ValueError('无此代码')
                with self._lock:
                    self._names[code] = wanted[code]
                    self._base[code] = {'prev': number(quotes[0].prev_close), 'close': number(quotes[0].last_done)}
                    first = latest(quotes[0], wanted[code], self._base[code])
                context.subscribe([code], [SubType.Quote])
            except Exception as exc:
                if auth_failure(exc): raise
                refused.add(code)
                self.log('longbridge: %s refused: %s' % (code, exc))
                continue
            active.add(code)
            # The SDK connects lazily; only an answered request proves the keys work.
            self.status = '已连接'
            if first:
                try: self.on_quote(first)
                except Exception: pass
        self.live = {wanted[c] for c in active if c in wanted}

    def _loop(self):
        attempt = 0
        while self.running:
            try:
                context, active, refused = self._connect(), set(), set()
                self.log('longbridge: context created')
                while self.running:
                    self._sync(context, active, refused)
                    if active: attempt = 0
                    time.sleep(.2)
                return
            except Exception as exc:
                attempt += 1
                self.status = describe(exc)
                self.log('longbridge: ' + str(exc))
                time.sleep(min(5 * 2 ** attempt, 300))
