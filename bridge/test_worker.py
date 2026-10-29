import os
import subprocess
import sys
import unittest
from stream import tick
from worker import apply_push, due_symbols, owner_alive, unavailable, with_note

# Real pushed trade captured 2026-10-28; see test_stream.py for the field layout.
WDC_TICK = tick('{"type":"pricing","message":"CgNXREMV1wzAQxigxo3OsGgqA05NUzAIOAJFNeVGwGWAHUXB2AEE9QKAGU5A/QIaclg/"}')


def snapshot(**extra):
    base = {'symbol': 'WDC', 'available': True, 'connected': True, 'price': 396.42,
            'quoteEpoch': 1793230000, 'session': '盘后', 'message': 'base'}
    base.update(extra)
    return base


class WorkerTests(unittest.TestCase):
    def test_active_quote_refreshes_after_three_seconds(self):
        self.assertEqual(due_symbols({'symbol': 'NVDA'}, {'NVDA': 100}, 103), ['NVDA'])

    def test_selected_and_next_only_not_entire_watchlist(self):
        self.assertEqual(due_symbols({'symbol': 'NVDA', 'nextSymbol': 'MU'}, {}, 100), ['NVDA', 'MU'])

    def test_fresh_cache_skips_fetch_and_invalid_symbols_never_request(self):
        self.assertEqual(due_symbols({'symbol': 'NVDA', 'nextSymbol': '../../bad'}, {'NVDA': 98}, 100), [])

    def test_failed_symbol_keeps_its_own_last_price(self):
        s = unavailable('MU', {'symbol': 'MU', 'price': 100}, 'offline')
        self.assertEqual((s['symbol'], s['price'], s['connected']), ('MU', 100, False))

    def test_wrong_symbol_cache_can_never_be_reused(self):
        s = unavailable('MU', {'symbol': 'NVDA', 'price': 900}, 'offline')
        self.assertIsNone(s.get('price'))

    def test_streamed_symbol_drops_to_http_heartbeat(self):
        request = {'symbol': 'WDC'}
        pushed_at = {'WDC': 1000}
        self.assertEqual(due_symbols(request, {'WDC': 1010}, 1020, {'WDC': 3}), ['WDC'])
        self.assertEqual(due_symbols(request, {'WDC': 1010}, 1020, {'WDC': 30}), [])

    def test_note_is_never_appended_twice(self):
        noted = with_note(snapshot(), '黄金现货暂不支持')
        self.assertEqual(noted['message'].count('黄金'), 1)
        self.assertEqual(with_note(noted, '黄金现货暂不支持')['message'].count('黄金'), 1)

    def test_push_replaces_price_and_marks_the_symbol_covered(self):
        quotes = {'WDC': snapshot()}
        last_push, pushed_at = {}, {}
        self.assertIsNotNone(apply_push(quotes, last_push, pushed_at, WDC_TICK, 1000))
        self.assertAlmostEqual(quotes['WDC']['price'], 384.1003, places=3)
        self.assertEqual(pushed_at['WDC'], 1000)

    def test_push_without_http_snapshot_is_never_cached(self):
        quotes = {}
        last_push, pushed_at = {}, {}
        self.assertIsNone(apply_push(quotes, last_push, pushed_at, WDC_TICK, 1000))
        self.assertEqual((quotes, pushed_at), ({}, {}))


    def test_worker_without_owner_never_exits_for_that_reason(self):
        self.assertTrue(owner_alive(0))

    def test_alive_launcher_keeps_the_worker(self):
        self.assertTrue(owner_alive(os.getpid()))

    def test_dead_launcher_releases_the_worker(self):
        gone = subprocess.Popen([sys.executable, '-c', 'pass'])
        gone.wait()
        self.assertFalse(owner_alive(gone.pid))


if __name__ == '__main__': unittest.main()
