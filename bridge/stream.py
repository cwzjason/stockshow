"""Yahoo public streaming quotes: server push instead of polling.

Field layout was verified against live messages on 2026-10-28 and is pinned by the
real byte fixtures in test_stream.py. Time arrives as epoch milliseconds * 2.
"""
import base64
import json
import math
import struct
import threading
import time
from datetime import datetime, timezone
from websockets.sync.client import connect
from public_quotes import ET

URL = 'wss://streamer.finance.yahoo.com/?version=2'
TIME_SCALE = 2000.0
HEARTBEAT = 10.0
POLL = 3.0
MAX_BACKOFF = 15.0
SYMBOL, PRICE, STAMP, CURRENCY, EXCHANGE, PERCENT, CHANGE = 1, 2, 3, 4, 5, 8, 12


def backoff(attempt):
    return min(2 ** attempt, MAX_BACKOFF)


def finite(value):
    return isinstance(value, float) and math.isfinite(value)


def varint(raw, index):
    shift, value = 0, 0
    while True:
        byte = raw[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7


def decode(raw):
    """Read one pricing protobuf. Returns None rather than a partial quote."""
    fields, index = {}, 0
    while index < len(raw):
        try:
            key, index = varint(raw, index)
            number, wire = key >> 3, key & 7
            if wire == 0:
                value, index = varint(raw, index)
            elif wire == 1:
                value = struct.unpack('<d', raw[index:index + 8])[0]; index += 8
            elif wire == 2:
                size, index = varint(raw, index)
                if index + size > len(raw): return None
                value = raw[index:index + size].decode('utf-8'); index += size
            elif wire == 5:
                value = struct.unpack('<f', raw[index:index + 4])[0]; index += 4
            else:
                return None
        except (IndexError, struct.error, UnicodeDecodeError):
            return None
        fields[number] = value
    return quote(fields)


def quote(fields):
    symbol, price = fields.get(SYMBOL), fields.get(PRICE)
    if not isinstance(symbol, str) or not symbol: return None
    if not finite(price) or price <= 0: return None
    percent = fields.get(PERCENT)
    change = fields.get(CHANGE)
    return {'symbol': symbol, 'price': price,
            'changePercent': round(percent, 4) if finite(percent) else None,
            'change': round(change, 4) if finite(change) else None,
            'epoch': fields[STAMP] / TIME_SCALE if STAMP in fields else 0,
            'currency': fields.get(CURRENCY) if isinstance(fields.get(CURRENCY), str) else '',
            'exchange': fields.get(EXCHANGE) if isinstance(fields.get(EXCHANGE), str) else ''}


def tick(envelope):
    """Turn one stream frame into a quote, or None when it carries no usable trade."""
    try:
        message = json.loads(envelope)
    except (ValueError, TypeError):
        return None
    if not isinstance(message, dict) or message.get('type') != 'pricing': return None
    try:
        raw = base64.b64decode(message.get('message') or '', validate=True)
    except (ValueError, TypeError):
        return None
    return decode(raw)


def merge(snapshot, pushed, now=None):
    """Apply a pushed trade on top of an HTTP snapshot. Identity and session never change."""
    if not snapshot or not pushed: return None
    if snapshot.get('symbol') != pushed['symbol']: return None
    if not snapshot.get('available') or not snapshot.get('price'): return None
    if pushed['change'] is None: return None
    stamp = pushed['epoch']
    if stamp <= 0 or stamp < snapshot.get('quoteEpoch', 0): return None
    age = max(0, int((now if now is not None else time.time()) - stamp))
    result = dict(snapshot)
    result.update(price=pushed['price'], reference=round(pushed['price'] - pushed['change'], 6),
                  changePercent=pushed['changePercent'], quoteEpoch=stamp,
                  available=True, connected=True, source='Yahoo 实时推送',
                  quoteTime=datetime.fromtimestamp(stamp, ET).strftime('%Y-%m-%d %H:%M:%S'),
                  fetchedAt=datetime.now(timezone.utc).isoformat(),
                  message='交易所推送的逐笔成交，非轮询。该笔成交距今 %d 秒。' % age)
    return result


def refresh_interval(symbol, ticks, now):
    """Push covers a symbol: HTTP drops to a heartbeat. Otherwise keep the fast poll.

    The heartbeat stays short: a silently dead stream must not leave an old quote on
    screen longer than the interval it replaced.
    """
    return HEARTBEAT if now - ticks.get(symbol, -1e9) < HEARTBEAT else POLL


class Stream:
    """Background WebSocket reader. Reconnects with capped backoff; never raises."""

    def __init__(self, on_quote, url=URL):
        self.on_quote = on_quote
        self.url = url
        self.symbols = []
        self.running = False
        self._pending = False
        self._thread = None

    def start(self, symbols=()):
        self.symbols = [s for s in dict.fromkeys(symbols)]
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def subscribe(self, symbols):
        symbols = [s for s in dict.fromkeys(symbols)]
        if symbols != self.symbols:
            self.symbols = symbols
            self._pending = True

    def stop(self):
        self.running = False

    def _loop(self):
        attempt = 0
        while self.running:
            try:
                with connect(self.url, open_timeout=10, ping_interval=15, ping_timeout=10) as ws:
                    ws.send(json.dumps({'subscribe': self.symbols}))
                    attempt = 0
                    while self.running:
                        if self._pending:
                            self._pending = False
                            ws.send(json.dumps({'subscribe': self.symbols}))
                        try:
                            envelope = ws.recv(timeout=5)
                        except TimeoutError:
                            continue
                        pushed = tick(envelope)
                        if pushed:
                            try: self.on_quote(pushed)
                            except Exception: pass
            except Exception:
                if not self.running: return
                attempt += 1
                time.sleep(backoff(attempt))
