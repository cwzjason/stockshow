"""Public WDC quote adapters. Source timestamps, not fetch time, identify trades."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from quotes import positive

ET = ZoneInfo('America/New_York')


def session(now, meta=None):
    epoch = now.timestamp()
    if meta:
        for key, label in [('pre', '盘前'), ('regular', '盘中'), ('post', '盘后')]:
            period = meta.get('currentTradingPeriod', {}).get(key, {})
            if period.get('start', 0) <= epoch < period.get('end', 0):
                return label, period['start']
        if meta.get('exchangeTimezoneName', 'America/New_York') not in ('America/New_York', 'US/Eastern'):
            return '休市', 0
    local = now.astimezone(ET)
    minute, weekday = local.hour * 60 + local.minute, local.weekday()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if minute >= 1200 and weekday in (6, 0, 1, 2, 3):
        return '夜盘', (midnight + timedelta(hours=20)).timestamp()
    if minute < 240 and weekday in (0, 1, 2, 3, 4):
        return '夜盘', (midnight - timedelta(hours=4)).timestamp()
    if weekday >= 5:
        return '休市', 0
    # Yahoo's exchange-provided intervals take precedence over a weekday clock,
    # including early closes and holidays (where its latest period is an old date).
    if meta:
        return '休市', 0
    if 240 <= minute < 570: return '盘前', (midnight + timedelta(hours=4)).timestamp()
    if 570 <= minute < 960: return '盘中', (midnight + timedelta(hours=9, minutes=30)).timestamp()
    if 960 <= minute < 1200: return '盘后', (midnight + timedelta(hours=16)).timestamp()
    return '休市', 0


def epoch(value):
    try:
        if isinstance(value, (int, float)): return float(value)
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def make_snapshot(source, label, start, candidates, now, symbol='WDC', currency='USD'):
    # Candidate tuple: source timestamp, price, reference. Never mix providers.
    valid = [(t, p, r) for t, p, r in candidates if t > 0 and p and
             t >= start and t <= now.timestamp() + 60]
    picked = max(valid, default=None, key=lambda x: x[0])
    stamp, price, reference = picked if picked else (0, None, None)
    age = max(0, now.timestamp() - stamp) if stamp else None
    return {'symbol': symbol, 'currency': currency, 'connected': True, 'available': picked is not None,
            'price': price, 'reference': reference,
            'changePercent': round((price / reference - 1) * 100, 4) if price and reference else None,
            'session': label, 'quoteEpoch': stamp,
            'quoteTime': datetime.fromtimestamp(stamp, ET).strftime('%Y-%m-%d %H:%M:%S') if stamp else '',
            'source': source, 'fetchedAt': now.astimezone(timezone.utc).isoformat(),
            'message': ('公开行情，约每 3 秒检查更新；不是交易所逐笔推送。' +
                        (f'该笔成交距今 {int(age)} 秒。' if age is not None else f'当前数据源未提供{label}报价。'))}


def from_yahoo(data, now, symbol='WDC'):
    chart = data.get('chart', {})
    if chart.get('error') or not chart.get('result'):
        raise ValueError('Yahoo 未返回 ' + symbol + ' 报价')
    result = chart['result'][0]; meta = result['meta']
    if meta.get('symbol', symbol).upper() != symbol.upper(): raise ValueError('股票代码不匹配')
    label, start = session(now, meta)
    if meta.get('instrumentType') == 'CRYPTOCURRENCY':
        label, start = '全天', now.timestamp() - 86400
    currency = 'YIELD' if symbol == '^TNX' else meta.get('currency', 'USD')
    regular = positive(meta.get('regularMarketPrice'))
    previous = positive(meta.get('previousClose') or meta.get('chartPreviousClose'))
    candidates = []
    if label in ('盘中', '休市', '全天'):
        candidates.append((epoch(meta.get('regularMarketTime')), regular, previous))
    if label == '休市':
        return make_snapshot('Yahoo Finance', label, start, candidates, now, symbol, currency)
    rows = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
    regular_end = meta.get('currentTradingPeriod', {}).get('regular', {}).get('end', 0)
    for stamp, price in zip(result.get('timestamp') or [], rows):
        reference = regular if label in ('盘后', '夜盘') or label == '休市' and stamp >= regular_end else previous
        candidates.append((epoch(stamp), positive(price), reference))
    return make_snapshot('Yahoo Finance', label, start, candidates, now, symbol, currency)


def from_robinhood(data, now, meta=None, symbol='WDC'):
    if data.get('symbol') != symbol: raise ValueError('Robinhood 未返回 ' + symbol + ' 报价')
    label, start = session(now, meta)
    regular = positive(data.get('last_trade_price'))
    previous = positive(data.get('adjusted_previous_close') or data.get('previous_close'))
    candidates = []
    if label in ('盘中', '休市'):
        candidates.append((epoch(data.get('venue_last_trade_time')), regular, previous))
    if label not in ('盘中', '休市'):
        candidates.append((epoch(data.get('venue_last_non_reg_trade_time')),
                           positive(data.get('last_non_reg_trade_price') or data.get('last_extended_hours_trade_price')),
                           previous if label == '盘前' else regular))
    return make_snapshot('Robinhood 公共报价', label, start, candidates, now, symbol)


def from_cnbc(data, now, meta=None, symbol='WDC'):
    quotes = data.get('ITVQuoteResult', {}).get('ITVQuote', [])
    if not quotes or quotes[0].get('symbol') != symbol or quotes[0].get('code') != '0':
        raise ValueError('CNBC 未返回 ' + symbol + ' 报价')
    q = quotes[0]; label, start = session(now, meta)
    regular = positive(q.get('last')); previous = positive(q.get('previous_day_closing'))
    candidates = []
    if label in ('盘中', '休市'):
        candidates.append((epoch(q.get('last_time')), regular, previous))
    extra = q.get('ExtendedMktQuote', {})
    expected = {'盘前': 'PRE_MKT', '盘后': 'POST_MKT'}
    if label in expected and extra.get('type') == expected[label] or label == '夜盘':
        candidates.append((epoch(extra.get('last_time')), positive(extra.get('last')), previous if label == '盘前' else regular))
    return make_snapshot('CNBC', label, start, candidates, now, symbol)


def choose(snapshots):
    if not snapshots: raise ValueError('所有公开数据源均连接失败')
    label = snapshots[0]['session']
    available = [s for s in snapshots if s['session'] == label and s['available']]
    return max(available, key=lambda s: s['quoteEpoch']) if available else snapshots[0]
