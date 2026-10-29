# Watchlist Ticker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import the actual moomoo watchlist and display its stocks in a small rotating ticker.
**Architecture:** Persist the list locally; WPF writes an atomic current/next selection request. Python returns per-symbol quote cache snapshots, independent of UI rotation.
**Tech Stack:** Existing WPF/.NET 9 and Python public quote adapters.
**Spec:** ../specs/2026-10-28-watchlist-design.md

## Global Constraints
- No charts, login automation, credentials, trading calls or fabricated watchlist entries.
- 276x32 ticker; five-second rotation; existing location/opacity retained.
- Fetch current/next only; each quote remains associated with its symbol and timestamp.

## Review Focus
- A slow fetch for A must never display A's price under B.
- One failed stock must not erase other cached stocks.
- Non-US trading hours must come from source periods, never US night classification.
- Imported table headers, numeric prices, duplicate symbols must not become false stock codes.
- Changing list during rotation must clamp selection and preserve usable UI.

### Task 1: Symbol-aware quote adapters and lazy worker
Files: bridge/public_quotes.py, bridge/worker.py, bridge/test_public_quotes.py, bridge/test_worker.py.
Interfaces: fetch_snapshot(symbol) -> snapshot with symbol; selection JSON {symbol,nextSymbol}; output JSON {quotes:{symbol:snapshot}}.
- [ ] Add tests for symbol mismatch and non-US off-hours; observe failing tests.
- [ ] Generalize adapters and worker to validated symbols, selected/next fetch, per-symbol cache and failure isolation.
- [ ] Run Python full suite and live two-symbol probe.

### Task 2: Watchlist configuration and native carousel
Files: src/StockBar/{Watchlist.cs,MainWindow.cs,Market.cs}, tests/StockBar.Checks/Program.cs, watchlist.json.
Interfaces: WatchlistConfig.Symbols/RotationSeconds, WatchlistParser.Parse(text), MarketFeed.Quotes.
- [ ] Add parser/identity/rotation tests; observe failure before implementation.
- [ ] Add editing/import dialog, rotation, wheel, pin, atomic selection requests and keyed snapshot reads.
- [ ] Run C# checks, publish and visually verify switching.

### Task 3: Actual moomoo list import and delivery
- [ ] Once user logs in, read/export only the self-selected watchlist and import actual symbols.
- [ ] Verify displayed label matches source quote, menu and rotation work, and no chart returns.
- [ ] Record actual import count, checks and any remaining login blocker in progress.md and README.
