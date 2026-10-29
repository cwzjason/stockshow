import unittest
from datetime import datetime, timezone
from public_quotes import from_yahoo, from_robinhood, from_cnbc, choose


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def fixture():
    return {'chart': {'result': [{'meta': {
        'regularMarketPrice': 100, 'previousClose': 80, 'regularMarketTime': 1793217600,
        'currentTradingPeriod': {'pre': {'start': 1793174400, 'end': 1793194200},
        'regular': {'start': 1793194200, 'end': 1793217600},
        'post': {'start': 1793217600, 'end': 1793232000}}},
        'timestamp': [1793219400], 'indicators': {'quote': [{'close': [105]}]}}], 'error': None}}


class PublicQuoteTests(unittest.TestCase):
    def test_symbol_parameter_validates_upstream_identity(self):
        f = fixture(); f['chart']['result'][0]['meta']['symbol'] = 'NVDA'
        s = from_yahoo(f, at('2026-10-28T20:31:00'), symbol='NVDA')
        self.assertEqual(s['symbol'], 'NVDA')
        with self.assertRaises(ValueError):
            from_yahoo(f, at('2026-10-28T20:31:00'), symbol='WDC')

    def test_non_us_market_does_not_invent_us_overnight(self):
        f = fixture(); f['chart']['result'][0]['meta'].update(symbol='0700.HK', exchangeTimezoneName='Asia/Hong_Kong')
        s = from_yahoo(f, at('2026-10-29T01:00:00'), symbol='0700.HK')
        self.assertEqual(s['session'], '休市')

    def test_yahoo_after_hours_uses_regular_close(self):
        s = from_yahoo(fixture(), at('2026-10-28T20:31:00'))
        self.assertEqual((s['price'], s['changePercent'], s['session']), (105, 5, '盘后'))

    def test_missing_night_quote_does_not_relabel_postmarket(self):
        s = from_yahoo(fixture(), at('2026-10-29T01:00:00'))
        self.assertIsNone(s['price'])
        self.assertEqual(s['session'], '夜盘')
        self.assertFalse(s['available'])

    def test_weekend_is_closed(self):
        s = from_yahoo(fixture(), at('2026-10-31T15:00:00'))
        self.assertEqual((s['session'], s['price'], s['changePercent']), ('休市', 100, 25))

    def test_regular_uses_timestamped_regular_quote(self):
        f = fixture(); f['chart']['result'][0]['meta']['regularMarketTime'] = 1793203200
        s = from_yahoo(f, at('2026-10-28T16:01:00'))
        self.assertEqual((s['price'], s['changePercent'], s['session']), (100, 25, '盘中'))

    def test_invalid_chart_point_is_not_a_quote(self):
        f = fixture(); f['chart']['result'][0]['indicators']['quote'][0]['close'] = [None]
        self.assertIsNone(from_yahoo(f, at('2026-10-28T20:31:00'))['price'])

    def test_robinhood_overnight_requires_a_night_trade(self):
        q = {'symbol': 'WDC', 'last_trade_price': '100', 'previous_close': '80',
             'venue_last_trade_time': '2026-10-28T19:59:59Z',
             'last_non_reg_trade_price': '102', 'venue_last_non_reg_trade_time': '2026-10-29T00:30:00Z'}
        s = from_robinhood(q, at('2026-10-29T01:00:00'))
        self.assertEqual((s['price'], s['changePercent'], s['session']), (102, 2, '夜盘'))
        q['venue_last_non_reg_trade_time'] = '2026-10-28T21:00:00Z'
        self.assertIsNone(from_robinhood(q, at('2026-10-29T01:00:00'))['price'])

    def test_cnbc_uses_full_extended_timestamp(self):
        d = {'ITVQuoteResult': {'ITVQuote': [{'symbol': 'WDC', 'code': '0', 'last': '100',
              'previous_day_closing': '80', 'curmktstatus': 'POST_MKT',
              'ExtendedMktQuote': {'last': '105', 'last_time': '2026-10-28T16:30:00.000-0400', 'type': 'POST_MKT'}}]}}
        s = from_cnbc(d, at('2026-10-28T20:31:00'))
        self.assertEqual((s['price'], s['changePercent']), (105, 5))

    def test_newest_source_wins_without_mixing_price_reference(self):
        a = from_yahoo(fixture(), at('2026-10-28T20:31:00'))
        b = dict(a, price=106, changePercent=6, quoteEpoch=1793219460, source='Other')
        self.assertEqual(choose([a, b])['price'], 106)

    def test_upstream_error_is_not_connected_success(self):
        with self.assertRaises(ValueError):
            from_yahoo({'chart': {'result': None, 'error': {'description': 'unavailable'}}}, at('2026-10-28T20:31:00'))


if __name__ == '__main__': unittest.main()
