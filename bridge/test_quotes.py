import unittest
from quotes import normalize


class QuotesTests(unittest.TestCase):
    def test_overnight_uses_overnight_price_and_regular_close(self):
        s = normalize({'last_price': 100, 'prev_close_price': 80, 'overnight_price': 102}, [], 'OVERNIGHT')
        self.assertEqual((s['price'], s['changePercent'], s['session']), (102, 2, '夜盘'))

    def test_regular_session_uses_regular_price_and_previous_close(self):
        s = normalize({'last_price': 84, 'prev_close_price': 80, 'pre_price': 99}, [], 'AFTERNOON')
        self.assertEqual((s['price'], s['changePercent'], s['session']), (84, 5, '盘中'))

    def test_after_hours_compares_to_regular_close(self):
        s = normalize({'last_price': 100, 'prev_close_price': 80, 'after_price': 105,
                       'after_time': '2026-10-27 16:20:00'}, [], 'AFTER_HOURS_BEGIN')
        self.assertEqual((s['price'], s['reference'], s['changePercent'], s['session']),
                         (105, 100, 5, '盘后'))

    def test_premarket_uses_previous_close(self):
        s = normalize({'last_price': 100, 'prev_close_price': 80, 'pre_price': 84}, [], 'PRE_MARKET_BEGIN')
        self.assertEqual((s['price'], s['changePercent']), (84, 5))

    def test_missing_extended_price_is_unavailable_not_regular_live(self):
        s = normalize({'last_price': 100, 'prev_close_price': 80, 'after_price': 0}, [], 'AFTER_HOURS_BEGIN')
        self.assertIsNone(s['price'])
        self.assertIsNone(s['changePercent'])

    def test_filters_blank_nonfinite_and_old_chart_points(self):
        rows = [{'time': '2026-10-26 15:00:00', 'cur_price': 90},
                {'time': '2026-10-27 09:30:00', 'cur_price': 100},
                {'time': '2026-10-27 09:31:00', 'cur_price': 0, 'is_blank': True},
                {'time': '2026-10-27 09:32:00', 'cur_price': float('nan')},
                {'time': '2026-10-27 16:30:00', 'cur_price': 105}]
        s = normalize({'last_price': 100, 'prev_close_price': 80}, rows, 'AFTER_HOURS_END')
        self.assertEqual(len(s['points']), 2)
        self.assertEqual(s['points'][1]['session'], '盘后')

    def test_zero_reference_never_divides_or_produces_nan(self):
        s = normalize({'last_price': 100, 'prev_close_price': 0}, [], 'MORNING')
        self.assertIsNone(s['changePercent'])

    def test_extended_hours_preserves_sdk_update_timestamp(self):
        s = normalize({'last_price': 100, 'prev_close_price': 80, 'after_price': 105,
                       'data_date': '2026-10-27', 'data_time': '16:20:00'}, [], 'AFTER_HOURS_BEGIN')
        self.assertEqual(s['quoteTime'], '2026-10-27 16:20:00')


if __name__ == '__main__':
    unittest.main()
