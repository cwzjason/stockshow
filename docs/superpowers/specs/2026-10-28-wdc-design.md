# WDC desktop ticker

Latest data-source direction: user explicitly permits other sources; replace OpenD default with keyless public Yahoo Finance, CNBC and Robinhood quote adapters. Poll every 15 seconds. Select the newest timestamped quote within the current session; show unavailable if no genuine overnight quote exists. Do not require moomoo, broker login or API keys. Keep the four-field weather-right ticker.

Latest user requirement supersedes chart requirements below: display ONLY WDC, price, percentage change, and 盘前/盘中/盘后/夜盘 status. Remove the hover chart and expanded panel entirely. Request only QUOTE permission/data from moomoo; no RT_DATA subscription. Keep the weather-right taskbar placement, settings, tray restore and explicit stale/connection indicators.

Approved in chat: WDC only, a small native Windows ticker beside the taskbar; hover for the day's extended-hours chart. No focus stealing or alerts. Adjustable opacity, movable placement, quick hide. Show source timestamps and disconnection explicitly. Never present sample data as live.

User correction: compact ticker must be IN the bottom taskbar's empty region immediately right of the weather widget. Use a 276 x 32 DIP borderless overlay, anchored 120 DIP from primary screen left, vertically centered in the bottom taskbar. Expand upward without moving the compact row. Use a neutral taskbar-like background. Preserve manual drag adjustment.

Approaches: native WPF overlay (selected), tray-only (too little visible information), embedded taskbar extension (OS compatibility cost). This is a new empty folder, not a Git repository.

Builder decisions: .NET 9 WPF, project-local Python moomoo SDK bridge, OpenD at loopback port 11111. No trading APIs. API permissions must be verified with the user's logged-in OpenD. No credentials stored. Chart uses US Eastern timestamps, source market state, and session-specific price references. Persist settings under this project. Native tray menu restores hidden UI and exits the program. Ctrl+Alt+W toggles visibility. No automatic startup registration in v1.

Limitations: live verification depends on OpenD login and WDC quote entitlement; do not claim it works until tested. Do not install paid services or alter moomoo settings.
