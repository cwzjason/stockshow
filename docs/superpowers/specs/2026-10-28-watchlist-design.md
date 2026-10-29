# Moomoo watchlist ticker

Latest user correction supersedes carousel requirements below: provide a search bar to switch freely instead of a fixed rotating list. Click ticker/search entry to open a focused small search window; query stock code or company name, select result to replace active symbol. No automatic carousel. Persist current and recent selections. Import actual 122 moomoo entries solely as optional local search suggestions, supplemented by Yahoo public search; accept symbols outside the list. Fetch only current symbol. Keep quote identity isolation and currency display.

User selected moomoo 自选列表 as the stock list. The preceding proposal was a five-second carousel with right-click selection/pinning; proceed with that scope. Keep the 276x32 weather-right ticker, four fields only, no charts.

Read/export the watchlist through the user's existing moomoo UI after they log in themselves. Never automate authentication, read credentials, or substitute example stocks for their list. If login is pending, implement independently and retain WDC as the existing entry until the actual import is possible.

Use project watchlist.json for the imported symbols, rotationSeconds=5. Provide an editable list/import dialog and right-click selection, pause/resume, and wheel navigation. Existing window position and opacity persist. No background changes to moomoo's watchlist.

Use keyed quote snapshots and explicit symbol checks to prevent one stock's price from appearing under another stock's label. Fetch selected and next stock only, cache per symbol, refresh active quotes every 15 seconds, respect stale status per quote. Support US tickers with three providers; Yahoo symbols for HK/A shares use source trading periods, without US overnight assumptions. Unsupported entries remain unavailable rather than fabricated.

Approaches: fetching every stock continuously would multiply request volume; a keyed lazy cache (selected) refreshes current/next without blocking UI. Read-only one-time watchlist import is selected; continuous account sync would require another authorized data channel.
