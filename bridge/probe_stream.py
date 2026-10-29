"""Probe which watchlist symbols Yahoo actually streams.

Yahoo delivers nothing for many non-US and thin symbols; those stay on HTTP polling.
Run: .venv/Scripts/python.exe bridge/probe_stream.py [seconds]
"""
import json
import sys
import time
from pathlib import Path
from stream import Stream

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
watchlist = json.loads(Path(__file__).resolve().parent.parent.joinpath('watchlist.json')
                       .read_text(encoding='utf-8-sig'))
symbols = [s for s in watchlist.get('symbols', []) if s[:1].isalpha()][:20]

delivered = {}
stream = Stream(lambda quote: delivered.__setitem__(quote['symbol'], quote))
stream.start(symbols)
deadline = time.time() + SECONDS
while time.time() < deadline:
    time.sleep(.5)
stream.stop()

print('subscribed %d symbols for %.0fs' % (len(symbols), SECONDS))
print('streamed  :', ' '.join(sorted(delivered)) or '(none)')
print('http only :', ' '.join(s for s in symbols if s not in delivered) or '(none)')
for symbol in sorted(delivered):
    quote = delivered[symbol]
    print('  %-10s %.4f  %s' % (symbol, quote['price'], quote['exchange']))
