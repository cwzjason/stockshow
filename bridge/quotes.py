"""Normalize quote-only moomoo data. All naive source times are US Eastern."""
import math
from datetime import datetime, timezone


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (ValueError, TypeError):
        return None


def point_session(time):
    clock = time[11:16]
    if clock < '04:00' or clock >= '20:00':
        return '夜盘'
    if clock < '09:30':
        return '盘前'
    return '盘中' if clock < '16:00' else '盘后'


def normalize(quote, points, market_state):
    state = str(market_state).split('.')[-1]
    regular = positive(quote.get('last_price'))
    previous = positive(quote.get('prev_close_price'))
    price, reference = regular, previous
    stamp = str(quote.get('data_time') or '')
    if len(stamp) == 8:
        stamp = str(quote.get('data_date') or '') + ' ' + stamp
    session = '休市'
    if state in ('PRE_MARKET_BEGIN', 'PRE_MARKET_END'):
        session, price, reference = '盘前', positive(quote.get('pre_price')), previous
        stamp = str(quote.get('pre_time') or stamp)
    elif state == 'AFTER_HOURS_BEGIN':
        session, price, reference = '盘后', positive(quote.get('after_price')), regular
        stamp = str(quote.get('after_time') or stamp)
    elif state in ('OVERNIGHT', 'NIGHT_OPEN'):
        session, price, reference = '夜盘', positive(quote.get('overnight_price')), regular
        stamp = str(quote.get('overnight_time') or stamp)
    elif state in ('MORNING', 'AFTERNOON'):
        session = '盘中'
    elif state not in ('CLOSED', 'AFTER_HOURS_END', 'NIGHT_END', 'NONE', 'REST', 'WAITING_OPEN'):
        session, price, stamp = '时段未知', None, ''
    clean = {}
    for row in points:
        time = str(row.get('time') or '')
        value = positive(row.get('cur_price'))
        try:
            datetime.strptime(time, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if value is not None and not row.get('is_blank', False):
            clean[time] = {'time': time, 'price': value, 'session': point_session(time)}
    # Day chart is explicitly a calendar day in Eastern time, never bridge-local time.
    latest_day = max((t[:10] for t in clean), default='')
    chart = [clean[t] for t in sorted(clean) if t[:10] == latest_day]
    change = round((price / reference - 1) * 100, 4) if price and reference else None
    return {'connected': True, 'price': price, 'reference': reference,
            'previousClose': previous, 'changePercent': change, 'session': session,
            'quoteTime': stamp, 'points': chart, 'chartDate': latest_day,
            'source': 'moomoo OpenD', 'message': '行情权限/延迟以 moomoo 为准',
            'fetchedAt': datetime.now(timezone.utc).isoformat()}
