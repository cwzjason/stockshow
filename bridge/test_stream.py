import unittest
from stream import decode, tick, merge, refresh_interval, Stream, backoff

# Real bytes captured from wss://streamer.finance.yahoo.com on 2026-10-28 (ET evening).
# Values below are what those bytes contain, verified against the HTTP snapshot.
WDC = 'CgNXREMV1wzAQxigxo3OsGgqA05NUzAIOAJFNeVGwGWAHUXB2AEE9QKAGU5A/QIaclg/'
NVDA = 'CgROVkRBFezRVUMYgK2LzrBoKgNOTVMwCDgCRbtrOb9lAK7Hv9gBBPUCANeDwP0Cffnxvw=='
BTC = ('CgdCVEMtVVNEFVucnkcY8OGJzrBoIgNVU0QqA0NDQzApOAFF3KYBP0iAwKCntwFVWFCfR10s5ZxHZQCbzEN'
       '9NtCdR7ABgMCgp7cB2AEE4AGAwKCntwHoAYDAoKe3AfIBA0JUQ4ECAAAA4HIsc0GJAgAAF38rx3dC9QIAm8xD/QLcpgE/')

SNAPSHOT = {'symbol': 'WDC', 'currency': 'USD', 'connected': True, 'available': True,
            'price': 396.42, 'reference': 396.42, 'changePercent': 0.0, 'session': '盘后',
            'quoteEpoch': 1793230000, 'quoteTime': '2026-10-28 16:00:00',
            'source': 'Yahoo Finance', 'message': 'm'}


class DecodeTests(unittest.TestCase):
    def test_real_wdc_message_recovers_symbol_price_and_change(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        self.assertEqual(quote['symbol'], 'WDC')
        self.assertAlmostEqual(quote['price'], 384.1003, places=3)
        self.assertAlmostEqual(quote['changePercent'], -3.1077, places=3)
        self.assertAlmostEqual(quote['change'], -12.3197, places=3)

    def test_time_field_is_epoch_milliseconds_times_two(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        self.assertAlmostEqual(quote['epoch'], 3586461492000 / 2000, delta=1)

    def test_change_amount_recovers_the_reference_the_source_used(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        self.assertAlmostEqual(quote['price'] - quote['change'], 396.42, places=2)

    def test_crypto_message_carries_currency_and_exchange(self):
        quote = tick('{"type":"pricing","message":"%s"}' % BTC)
        self.assertEqual((quote['symbol'], quote['currency']), ('BTC-USD', 'USD'))
        self.assertAlmostEqual(quote['price'], 81208.7109, places=2)

    def test_nvda_message_recovers_nasdaq_exchange(self):
        quote = tick('{"type":"pricing","message":"%s"}' % NVDA)
        self.assertEqual((quote['symbol'], quote['exchange']), ('NVDA', 'NMS'))

    def test_heartbeat_envelope_never_becomes_a_quote(self):
        self.assertIsNone(tick('{"type":"heartbeat","message":""}'))

    def test_truncated_payload_never_yields_a_quote(self):
        self.assertIsNone(decode(bytes([0x0A, 0x04]) + b'NVDA' + bytes([0x15, 0x00])))

    def test_message_without_price_never_yields_a_quote(self):
        self.assertIsNone(decode(bytes([0x0A, 0x04]) + b'NVDA'))

    def test_malformed_json_never_raises(self):
        self.assertIsNone(tick('not json'))


class MergeTests(unittest.TestCase):
    def test_push_updates_price_reference_and_percentage(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        merged = merge(SNAPSHOT, quote)
        self.assertAlmostEqual(merged['price'], 384.1003, places=3)
        self.assertAlmostEqual(merged['reference'], 396.42, places=2)
        self.assertEqual(merged['source'], 'Yahoo 实时推送')

    def test_push_never_changes_identity_or_session(self):
        quote = tick('{"type":"pricing","message":"%s"}' % NVDA)
        self.assertIsNone(merge(SNAPSHOT, quote))

    def test_older_trade_never_overwrites_newer_quote(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        self.assertIsNone(merge(dict(SNAPSHOT, quoteEpoch=quote['epoch'] + 60), quote))

    def test_unavailable_snapshot_cannot_be_merged(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        self.assertIsNone(merge(dict(SNAPSHOT, available=False, price=None), quote))

    def test_merged_quote_reports_its_own_age(self):
        quote = tick('{"type":"pricing","message":"%s"}' % WDC)
        merged = merge(SNAPSHOT, quote, now=quote['epoch'] + 7)
        self.assertIn('距今 7 秒', merged['message'])


class SchedulingTests(unittest.TestCase):
    def test_streamed_symbol_only_heartbeats_over_http(self):
        self.assertEqual(refresh_interval('WDC', {'WDC': 1000}, 1005), 10)

    def test_symbol_without_push_keeps_fast_polling(self):
        self.assertEqual(refresh_interval('^TNX', {'WDC': 1000}, 1005), 3)

    def test_silently_dead_stream_falls_back_to_fast_polling(self):
        self.assertEqual(refresh_interval('WDC', {'WDC': 1000}, 1010), 3)

    def test_backoff_grows_but_stays_bounded(self):
        self.assertEqual([backoff(i) for i in range(6)], [1, 2, 4, 8, 15, 15])


class LifecycleTests(unittest.TestCase):
    def test_stop_before_start_is_safe(self):
        stream = Stream(lambda quote: None)
        stream.stop()
        self.assertFalse(stream.running)


if __name__ == '__main__':
    unittest.main()
