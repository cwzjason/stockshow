import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from longbridge_feed import to_longbridge, load_credentials, pushed, latest, epoch_of, LongbridgeFeed
from stream import merge
from worker import apply_push

BASE = {'prev': 200.0, 'close': 210.0}
NOW = datetime(2026, 10, 28, 21, 0, tzinfo=timezone.utc).timestamp()
STAMP = datetime(2026, 10, 28, 20, 59, 58, tzinfo=timezone.utc)
SNAPSHOT = {'symbol': 'NVDA', 'currency': 'USD', 'connected': True, 'available': False,
            'price': None, 'reference': None, 'session': '盘后', 'quoteEpoch': 0, 'message': 'm'}


class SymbolTests(unittest.TestCase):
    def test_us_stock_gets_market_suffix(self):
        self.assertEqual(to_longbridge('NVDA'), 'NVDA.US')

    def test_share_class_dash_becomes_dot(self):
        self.assertEqual(to_longbridge('BRK-B'), 'BRK.B.US')

    def test_hong_kong_drops_leading_zeros(self):
        self.assertEqual(to_longbridge('0700.HK'), '700.HK')

    def test_shanghai_and_shenzhen_map_to_longbridge_markets(self):
        self.assertEqual((to_longbridge('600519.SS'), to_longbridge('000001.SZ')), ('600519.SH', '000001.SZ'))

    def test_markets_longbridge_lacks_stay_on_public_sources(self):
        for symbol in ['^TNX', 'BTC-USD', 'CL=F', '005930.KS', '^KS11', None]:
            self.assertIsNone(to_longbridge(symbol), symbol)


class CredentialTests(unittest.TestCase):
    def write(self, data):
        folder = tempfile.mkdtemp()
        path = Path(folder) / 'longbridge.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_complete_file_enables_the_feed(self):
        path = self.write({'appKey': 'k', 'appSecret': 's', 'accessToken': 't'})
        self.assertEqual(load_credentials(path, {})['accessToken'], 't')

    def test_untouched_template_stays_disabled(self):
        path = self.write({'appKey': '<App Key>', 'appSecret': '<App Secret>', 'accessToken': '<Access Token>'})
        self.assertIsNone(load_credentials(path, {}))

    def test_missing_file_falls_back_to_environment(self):
        env = {'LONGBRIDGE_APP_KEY': 'k', 'LONGBRIDGE_APP_SECRET': 's', 'LONGBRIDGE_ACCESS_TOKEN': 't'}
        self.assertIsNotNone(load_credentials(Path(tempfile.mkdtemp()) / 'none.json', env))

    def test_partial_credentials_never_start_a_connection(self):
        self.assertIsNone(load_credentials(self.write({'appKey': 'k'}), {}))


class PushTests(unittest.TestCase):
    def test_regular_trade_compares_with_previous_close(self):
        q = pushed('NVDA', 220.0, 'TradeSession.Intraday', STAMP, BASE, NOW)
        self.assertEqual((q['session'], q['changePercent']), ('盘中', 10.0))

    def test_post_and_overnight_compare_with_regular_close(self):
        for name, label in [('TradeSession.Post', '盘后'), ('TradeSession.Overnight', '夜盘')]:
            q = pushed('NVDA', 231.0, name, STAMP, BASE, NOW)
            self.assertEqual((q['session'], q['changePercent']), (label, 10.0))

    def test_pre_market_compares_with_previous_close(self):
        self.assertEqual(pushed('NVDA', 190.0, 'Pre', STAMP, BASE, NOW)['changePercent'], -5.0)

    def test_change_recovers_the_reference_like_a_yahoo_push(self):
        q = pushed('NVDA', 220.0, 'Intraday', STAMP, BASE, NOW)
        self.assertAlmostEqual(q['price'] - q['change'], 200.0)

    def test_unknown_session_or_bad_price_is_dropped(self):
        self.assertIsNone(pushed('NVDA', 220.0, 'TradeSession.Unknown', STAMP, BASE, NOW))
        self.assertIsNone(pushed('NVDA', 0, 'Intraday', STAMP, BASE, NOW))
        self.assertIsNone(pushed('NVDA', 220.0, 'Intraday', STAMP, {'prev': None}, NOW))

    def test_naive_utc_timestamp_is_not_shifted_into_the_future(self):
        naive = STAMP.replace(tzinfo=None)
        self.assertLessEqual(epoch_of(naive, NOW), NOW + 60)
        self.assertGreater(epoch_of(naive, NOW), NOW - 86400)

    def test_broker_push_sets_session_and_source_on_merge(self):
        q = pushed('NVDA', 231.0, 'Overnight', STAMP, BASE, NOW)
        merged = merge(SNAPSHOT, q)
        self.assertEqual((merged['session'], merged['source'], merged['price']), ('夜盘', '长桥实时推送', 231.0))
        self.assertAlmostEqual(merged['reference'], 210.0)

    def test_yahoo_push_still_never_changes_session(self):
        q = dict(pushed('NVDA', 231.0, 'Overnight', STAMP, BASE, NOW))
        del q['session'], q['source']
        self.assertEqual(merge(SNAPSHOT, q)['session'], '盘后')

    def test_first_push_before_http_is_kept_for_the_later_merge(self):
        q = pushed('NVDA', 231.0, 'Overnight', STAMP, BASE, NOW)
        quotes, last_push, pushed_at = {}, {}, {}
        self.assertIsNone(apply_push(quotes, last_push, pushed_at, q, 0))
        self.assertEqual((quotes, pushed_at), ({}, {}))
        self.assertIs(last_push['NVDA'], q)

    def test_pulled_quote_picks_the_newest_session(self):
        early = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
        quote = SimpleNamespace(last_done=210.0, timestamp=early, pre_market_quote=None,
                                post_market_quote=SimpleNamespace(last_done=215.0, timestamp=STAMP),
                                overnight_quote=None)
        q = latest(quote, 'NVDA', BASE, NOW)
        self.assertEqual((q['session'], q['price'], q['epoch']), ('盘后', 215.0, STAMP.timestamp()))


class FeedTests(unittest.TestCase):
    def test_push_for_unsubscribed_code_is_ignored(self):
        seen = []
        feed = LongbridgeFeed(seen.append, {})
        feed._on_push('NVDA.US', SimpleNamespace(last_done=1.0, trade_session='Intraday', timestamp=STAMP))
        self.assertEqual(seen, [])

    def test_regular_push_moves_the_after_hours_reference(self):
        seen = []
        feed = LongbridgeFeed(seen.append, {})
        feed._names['NVDA.US'], feed._base['NVDA.US'] = 'NVDA', dict(BASE)
        feed._on_push('NVDA.US', SimpleNamespace(last_done=222.0, trade_session='Intraday', timestamp=STAMP))
        self.assertEqual((seen[0]['symbol'], feed._base['NVDA.US']['close']), ('NVDA', 222.0))

    def test_not_covered_until_connected_and_subscribed(self):
        feed = LongbridgeFeed(lambda q: None, {})
        self.assertFalse(feed.covers('NVDA'))
        feed.status, feed.live = '已连接', {'NVDA'}
        self.assertTrue(feed.covers('NVDA'))


if __name__ == '__main__': unittest.main()
