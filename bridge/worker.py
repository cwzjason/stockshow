"""Lazy public quote cache for the active and next watchlist symbols.

Streaming push is the primary path; HTTP becomes a metadata heartbeat while push
delivers, and stays the only source for symbols Yahoo does not stream.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import time
import urllib.parse
import urllib.request
from public_quotes import from_yahoo, from_robinhood, from_cnbc, choose
from stream import Stream, merge, refresh_interval
from longbridge_feed import LongbridgeFeed, load_credentials


def valid_symbol(symbol):
    return isinstance(symbol, str) and bool(re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=\-]{0,24}', symbol))


def source_urls(symbol):
    escaped = urllib.parse.quote(symbol, safe='')
    urls = {'yahoo': f'https://query1.finance.yahoo.com/v8/finance/chart/{escaped}?interval=1m&range=1d&includePrePost=true'}
    if re.fullmatch(r'[A-Z][A-Z0-9\-]{0,9}', symbol):
        urls['cnbc'] = f'https://quote.cnbc.com/quote-html-webservice/quote.htm?symbols={escaped}&requestMethod=itv&noform=1&fund=1&exthrs=1&output=json'
        urls['robinhood'] = f'https://api.robinhood.com/quotes/{escaped}/'
    return urls


def write_snapshot(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def fetch_snapshot(symbol='WDC'):
    if not valid_symbol(symbol): raise ValueError('无效股票代码')
    payloads, errors = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(fetch, url): name for name, url in source_urls(symbol).items()}
        for task in as_completed(pending):
            name = pending[task]
            try: payloads[name] = task.result()
            except Exception as exc: errors.append(name + ': ' + str(exc))
    now = datetime.now(timezone.utc)
    meta = None
    try: meta = payloads['yahoo']['chart']['result'][0]['meta']
    except (KeyError, TypeError, IndexError): pass
    snapshots = []
    for name, adapter in [('yahoo', from_yahoo), ('cnbc', from_cnbc), ('robinhood', from_robinhood)]:
        if name not in payloads: continue
        try:
            snapshots.append(adapter(payloads[name], now, symbol=symbol) if name == 'yahoo'
                             else adapter(payloads[name], now, meta, symbol=symbol))
        except Exception as exc: errors.append(name + ': ' + str(exc))
    result = choose(snapshots)
    if errors: result['message'] += ' 部分备用源暂不可用。'
    return result


def due_symbols(request, attempted, now, intervals=None):
    intervals = intervals or {}
    result = []
    for symbol in [request.get('symbol'), request.get('nextSymbol')]:
        if valid_symbol(symbol) and symbol not in result and now - attempted.get(symbol, -1000) >= intervals.get(symbol, 3):
            result.append(symbol)
    return result


STILL_ACTIVE = 259


def owner_alive(pid):
    """False once the launcher that started this worker is gone, so a killed UI
    cannot leave an orphan worker writing quotes nobody displays."""
    if pid <= 0 or os.name != 'nt': return True
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle: return False
    code = ctypes.c_ulong()
    try:
        running = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return bool(running) and code.value == STILL_ACTIVE


def with_note(snapshot, note):
    if not note: return snapshot
    result = dict(snapshot)
    if not result.get('message', '').endswith(note):
        result['message'] = result.get('message', '') + ' ' + note
    return result


def apply_push(quotes, last_push, pushed_at, pushed, now):
    """Fold a pushed trade into the cached quote. Only a real merge counts as coverage.

    The trade is kept even when no HTTP snapshot exists yet: a broker's first push
    arrives before the first HTTP response and is merged once that response lands.
    """
    previous = last_push.get(pushed['symbol'])
    if not previous or pushed['epoch'] >= previous['epoch']:
        last_push[pushed['symbol']] = pushed
    merged = merge(quotes.get(pushed['symbol']), pushed)
    if not merged: return None
    pushed_at[pushed['symbol']] = now
    quotes[pushed['symbol']] = merged
    return merged


def unavailable(symbol, previous, message):
    result = dict(previous) if previous.get('symbol') == symbol else {}
    result.update(symbol=symbol, connected=False, message='公开行情暂不可用：' + message,
                  fetchedAt=datetime.now(timezone.utc).isoformat())
    return result


def read_json(path, fallback):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return fallback


def run(path, once=False, symbols=None, owner=0):
    root = Path(__file__).resolve().parent.parent
    request_path = root / 'runtime' / 'selection.json'
    quotes, attempted = {}, {}
    request = {'symbol': (symbols or ['WDC'])[0], 'nextSymbol': (symbols or ['WDC'])[-1]}
    if once:
        for symbol in dict.fromkeys(symbols or ['WDC']):
            try: quotes[symbol] = fetch_snapshot(symbol)
            except Exception as exc: quotes[symbol] = unavailable(symbol, {}, str(exc))
        write_snapshot(path, {'quotes': quotes})
        return
    ticks = queue.SimpleQueue()
    last_push, pushed_at = {}, {}
    stream = Stream(ticks.put)
    broker, credentials, checked = None, None, -1e9
    held = []
    providers = {'longbridge': '未配置'}

    def publish():
        write_snapshot(path, {'quotes': quotes, 'providers': providers})

    def log(message): print(message, flush=True)

    publish()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {}
        try:
            stream.start([s for s in (request.get('symbol'), request.get('nextSymbol')) if valid_symbol(s)])
            while owner_alive(owner):
                request = read_json(request_path, request)
                config = read_json(root / 'watchlist.json', {})
                unsupported = config.get('unsupported', {})
                notes = config.get('notes', {})
                now = time.monotonic()
                active = [s for s in (request.get('symbol'), request.get('nextSymbol')) if valid_symbol(s)]
                # Credentials are re-read every few seconds, so pasting a key needs no restart.
                if now - checked >= 3:
                    checked = now
                    found = load_credentials(root / 'runtime' / 'longbridge.json')
                    if found != credentials:
                        if broker: broker.stop()
                        credentials = found
                        broker = LongbridgeFeed(ticks.put, found, log) if found else None
                        if broker: broker.start(active)
                if broker: broker.subscribe(active)
                changed = providers.get('longbridge') != (broker.status if broker else '未配置')
                providers['longbridge'] = broker.status if broker else '未配置'
                # The broker push is the better feed; Yahoo only streams what it does not cover.
                stream.subscribe([s for s in active if not (broker and broker.covers(s))])
                while held or not ticks.empty():
                    pushed = held.pop() if held else ticks.get()
                    if apply_push(quotes, last_push, pushed_at, pushed, now) is None: continue
                    symbol = pushed['symbol']
                    quotes[symbol] = with_note(quotes[symbol], notes.get(symbol))
                    changed = True
                if changed: publish()
                intervals = {s: refresh_interval(s, pushed_at, now)
                             for s in (request.get('symbol'), request.get('nextSymbol')) if valid_symbol(s)}
                for symbol in due_symbols(request, attempted, now, intervals):
                    if symbol in pending.values(): continue
                    if symbol in unsupported:
                        quotes[symbol] = dict(symbol=symbol, connected=True, available=False, session='不支持',
                            message=unsupported[symbol], fetchedAt=datetime.now(timezone.utc).isoformat())
                        attempted[symbol] = now
                        publish()
                    elif len(pending) < 2:
                        attempted[symbol] = now
                        pending[pool.submit(fetch_snapshot, symbol)] = symbol
                for task in list(pending):
                    if not task.done(): continue
                    symbol = pending.pop(task)
                    try: fresh = task.result()
                    except Exception as exc: fresh = unavailable(symbol, quotes.get(symbol, {}), str(exc))
                    # A pushed trade newer than the HTTP response wins. Currency always
                    # comes from HTTP; session too, unless a broker push named it.
                    pushed = last_push.get(symbol)
                    if pushed and pushed['epoch'] >= fresh.get('quoteEpoch', 0):
                        fresh = merge(fresh, pushed) or fresh
                    quotes[symbol] = with_note(fresh, notes.get(symbol))
                    attempted[symbol] = time.monotonic() + (12 if not quotes[symbol].get('connected') else 0)
                    publish()
                # Wake the moment a push arrives instead of sleeping a fixed tick.
                try: held.append(ticks.get(timeout=.1))
                except queue.Empty: pass
        finally:
            stream.stop()
            if broker: broker.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--symbols', default='WDC')
    parser.add_argument('--owner', type=int, default=0, help='pid of the UI; worker exits when it dies')
    args = parser.parse_args()
    run(args.output, args.once, args.symbols.split(','), args.owner)
