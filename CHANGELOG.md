# Changelog

## 0.8.0 - 2026-08-08

- Added tarkov.dev's `pvp-season` game mode as “赛季服” across price lookup, 48-hour history, settings, the F9 in-raid controller, cache diagnostics, tracked crafts/barters, developer OCR tools, and packaged seed data.
- Kept seasonal refreshes on tarkov.dev's JSON API because its GraphQL `GameMode` enum still exposes only PvP/PvE; an accepted GraphQL fallback refreshes those two modes while retaining the last valid seasonal cache.
- Added a startup software-update check backed by a small GitHub Release manifest, plus a manual `Help -> Check for updates` action.
- Added an explicit update prompt, background download progress, cancellation and resume support, release notes, exact asset-size checks, SHA-256 verification, and archive-structure validation.
- Added a separately packaged Windows updater that waits for the main app to exit, preserves portable user data, replaces the managed runtime, rolls back on failure, and restarts the app with a success/failure result notice.
- Added mirror-ready manifest URLs so a mainland China object-storage download source can be introduced later without changing installed clients; GitHub remains the initial source and manual download remains available after network failures.
- Extended the repeatable release build to produce `update-manifest.json` and include `EFT Raid Assistant Updater.exe` in the portable ZIP.
- Treated a missing manifest on pre-updater releases as a normal “not published yet” state instead of exposing a raw HTTP 404 error.

## 0.7.2 - 2026-08-07

- Added an immediate local listing suggestion that uses `lastLowPrice` directly, shows the 24-hour average and API sample time alongside it, and warns instead of silently changing the suggestion when market depth is thin or the references diverge.
- Added an optional per-item smart listing estimate using 48 hours of log-price history, time/liquidity weighting, robust median/MAD outlier handling, and confirmed multi-snapshot regime shifts for events or early-wipe demand spikes.
- Kept smart history off by default and asynchronous when enabled; the recent-low card appears first, history is cached for 15 minutes, and every usable smart estimate updates the suggested listing/net proceeds while its confidence remains visible.
- Redesigned price cards around three after-fee sale regions (`flea better`, `trader better`, or `close`), suggested listing/net proceeds, both API references, confidence, sample time, and compact risk notices; removed the visible floor value, routine volatility ranges, and redundant single-slot value text.
- Changed value-per-slot colors and card borders to follow the conservative realizable net value, including the best trader floor, so uncertain smart estimates cannot inflate the loot tier.
- Redesigned tracked-recipe callouts as a compact, independently tinted in-raid reminder between the sale advice and API details; it names the required material, shows at most three uses, and summarizes overflow without an unusable scroll area while leaving the outer value-tier border untouched. Checking, deleting, or clearing tracked recipes now updates checkbox state without rebuilding and collapsing the browsed recipe tree.
- Added Night Blue and Sakura Pink application themes for the desktop shell while keeping every in-raid overlay on the existing dark immersive palette.

- Reworked trader restock reminders around one live state source: the main table and a non-focus aggregate overlay now update every active trader countdown once per second.
- Integrated the existing reminder popup and F7 behavior into the aggregate countdown overlay; triggered traders are highlighted, while an explicit user hide remains respected for later alerts.
- Removed editable trader-timer fields and the secondary schedule button; OCR now atomically replaces reminders for the currently selected traders.
- Changed strict cursor-anchored tooltip validation to treat text density only as an empty-box check; short names such as `节能灯泡` now proceed to OCR and local item matching instead of being rejected before OCR.
- Made Tarkov 1.1 tooltip height select the OCR layout deterministically: normal-height boxes stay single-line, while tall boxes use joined line recognition; also covered 720p borders, maximum-width 4K tooltips, and ambiguous short-name rejection.
- Added Tarkov 1.1 flea-market fee estimation using the current 5% item and requirement rates, Intelligence Center 3, and Hideout Management discounts; price cards now compare after-fee flea proceeds with the best trader price.
- Added Intelligence Center (0-3) and Hideout Management (0-50) inputs to first-run setup and Settings; both ship as 0 rather than using the developer's profile.
- Validated the fee implementation against 18 in-game measurements for Medical tools and WD-40 (100ml), with exact rouble-for-rouble agreement across listings from 1,000 to 100,000 RUB.
- Restored price-tooltip recognition for Tarkov 1.1's wider/taller tooltip layout, including wrapped item names, while retaining empty-box rejection and legacy-tooltip compatibility.
- Anchored Tarkov 1.1 tooltip detection to the cursor-left offset or visible client right edge, with a hard maximum width, so inventory label rows no longer outrank the real tooltip.
- Preserved item names containing navigation words such as `地图`, and reduced false short-name matches from noisy OCR strings such as `绳索电路板医`.
- Reworked the price overlay into a three-card animated stack: existing cards ease downward before a delayed, gentler new-result fade, and the oldest card moves out while fading when the stack overflows.
- Temporarily hides only price cards intersecting the active capture region, using native window pixels on high-DPI displays and waiting for the Windows compositor before capture; it then restores their position, opacity, animation, and remaining lifetime so partially covered upper-right tooltips remain queryable.
- Added a two-stage character-screen guard: when a dragged container obscures the Equipment tab, the Achievements tab can provisionally confirm the page, but lookup still requires strict tooltip geometry and a unique local item match.
- Corrected top-edge tooltip handling to use client-top clamping, matching Tarkov's right-edge behavior; below-cursor boxes are no longer accepted as a special case.
- Changed tooltip OCR into a lazy local-match cascade: single-line and split double-line recognition stop on the first unique exact item, while threshold and inverted variants run only when needed.
- Replaced price cards for ammunition and ammo boxes with tarkov.dev JSON ballistics: damage, penetration, armor damage, velocity, projectile count, and non-zero recoil/accuracy modifiers, with penetration-tier colors and a spectrum accent above 70 penetration.
- Restyled checkboxes with theme-matched surfaces, high-visibility checked states, and full-row highlighting for feature selection; dark mode no longer uses a stark white indicator box.
- Reorganized Settings around user tasks: common behavior, module selection, price lookup, reminders/overlays, shortcuts, and a separated advanced area for diagnostics, capture calibration, and Gamma safety.
- Repositioned the equipment-tab check for Tarkov 1.1's stretched navigation bar, with automatic migration of the old default ROI and a legacy-layout fallback.
- Fixed Tarkov window selection to prefer the foreground `EscapeFromTarkov` process, reject the launcher, and log the selected window title, process, and origin for diagnostics.
- Added 16:10 capture regression coverage confirming that Tarkov scales the inventory UI across the full client area without assumed letterboxing.

## 0.7.0 - 2026-08-02

- Reduced in-raid lookup CPU spikes by limiting RapidOCR to a configurable 1/2/4-thread budget, with 2 threads as the default.
- Removed normal lookup screenshot filesystem round-trips, retained diagnostic images only on failures, and stopped forcing a full garbage collection after every worker.
- Reused the already loaded price-mode cache instead of reparsing and reindexing all item data on every lookup.
- Vectorized Tooltip border detection and added staged lookup timing diagnostics; warm in-game lookups now normally complete in roughly 60–100 ms on the validated system.
- Kept periodic idle cleanup away from Tarkov foreground sessions and preserved the short-lived inventory-state cache.

- Fixed the collapsed main log so it shrinks the splitter pane and stays pinned to the bottom edge instead of leaving a floating log header in the middle of the window.
- Added light (default), dark, and high-contrast application themes with immediate Settings switching while keeping in-raid translucent overlays dark.
- Changed tracked-material notices to use the title “制作/兑换配方”, emphasize the target product, and show the current material as “需求：N 个”.
- Removed the Gamma section from the F9 overlay when the display-filter feature is disabled.
- Added Windows display-output enumeration, persisted per-display targeting, monitor/adapter labels, a nonvisual Gamma Ramp read/write probe, and target-safe restore/switch behavior for multi-monitor systems.
- Disabled the global color-matrix fallback for explicit per-display operations so a rejected target cannot silently modify every screen.
- Fixed the blank white area after the last recipe-tree header column by theming the full header viewport, horizontal scrollbar, and scroll-area corner; added an offscreen pixel regression test.
- Split frozen bundled resources from portable writable data so packaged recipes, aliases, icons, and seed caches load from `_internal`, while user config/cache/debug files remain beside the executable.
- Added config migration and atomic writes; older installs no longer retain the indefinite startup-price-refresh skip.
- Changed performance-mode startup refresh to skip fresh caches but perform a low-bandwidth ETag check when the configured staleness threshold is exceeded.
- Added a data-status dashboard with price-cache freshness, alias, recipe, hideout, and last-error status plus a bounded diagnostic-zip exporter.
- Changed feature toggles to rebuild the application shell and runtime modules immediately without restarting.
- Added persistence for main-window geometry, resizable/collapsible log height, recipe column widths, category expansion, and both in-raid overlay positions.
- Changed first-run defaults to enable only core price lookup and marked experimental modules as Beta.
- Added atomic hideout requirement/progress writes and frozen seed-cache fallback for first launch.
- Added a repeatable development-package script covering compile, tests, source/exe smoke checks, PyInstaller, zip validation, and SHA-256 generation.

- Fixed live font scaling in recipe trees, added proportional tree-row spacing, and enlarged the main-window defaults.
- Renamed recipe notes to a compact task-dependency column and made every recipe tree column user-resizable.
- Added a first-run feature setup dialog and Settings feature toggles so users can enable only the panels they need; changes take effect immediately.
- Changed feature toggles to be hard module gates: disabled modules do not create their runtime managers, register hotkeys, start background refreshes, or apply display filters.
- Changed Settings to open on the hotkey tab by default and moved low-frequency capture ROI/manual resolution controls into a collapsed advanced capture section.
- Added a dark, translucent upper-right in-raid control panel (`F9`) for live price mode, display language, overlay timing, panel opacity, and Gamma adjustment.
- Added a lower-left raid log (`F10`) that shows without proactively taking focus, then supports click, wheel/scrollbar history navigation, and title-bar dragging.
- Added an optional offline recipe-tracking module using tarkov.dev's game-handbook category hierarchy, with a category browser and product → concrete recipe → per-material rows.
- Added a tracked-recipe overview for unified untracking, multi-selection deletion, clearing, and recipe-notice accent-color customization.
- Simplified recipe rows so product recipe counts and material requirements stay beside their names, recipe actions read naturally as source/level plus craft or barter, tools use a dedicated check column, and output/material quantities use distinct colors.
- Added a live 9–18pt main-interface font-size setting, with the default raised to 11pt.
- Added English trader names, `hh:mm:ss` craft durations, barter buy limits, and localized task-unlock notes backed by exact task IDs from the bundled tarkov.dev snapshot.
- Changed tracked-material price notices into a separately bordered nested section below the normal price content, listing every related product plus trader/station level and current-item quantity.
- Bundled versioned PvE/PvP craft and trader-barter snapshots generated from tarkov.dev's static JSON endpoints; runtime recipe lookup is local-only.
- Added a shared UI theme, settings store, and log event bus as the first stage of splitting the desktop shell away from the monolithic main-window implementation.
- Removed the redundant extra daemon thread previously created for every global-hotkey press; Qt-bound actions now cross into the UI through signals directly.
- Added an explicit on/off flow for display enhancement and a Windows full-screen color-matrix fallback when the display driver rejects Gamma Ramp access.
- Added Gamma tuning sliders, curve preview, named preset save/delete, and a mouse-interactive always-on-top tuning window for in-game live adjustment.
- Added explicit Gamma preset creation from the current slider values in both the main panel and the in-game tuning window.
- Added optional per-preset Gamma hotkeys so each saved display profile can be applied directly in raid without cycling through other presets.
- Changed hotkey settings to capture the next key press directly, detect conflicts, and allow replacing an existing binding.
- Changed Gamma live tuning to apply silently while dragging sliders so visible logs and feedback toasts only appear for explicit hotkey toggles/restores or important safety events.
- Added Gamma eye-care mode: when neither Tarkov nor the assistant UI is active, the app can automatically restore the original display state and show a one-time reminder.
- Changed the visible log into a persistent, resizable and collapsible main-window section shared by all feature panels, with automatic scrolling to the newest entry.
- Hid foreground-window rejection messages from the visible log to avoid spam while users alt-tab or chat outside the game.
- Added a performance settings tab with visible-log line limits, background-worker concurrency limits, worker-finished memory cleanup, periodic idle cleanup, and cache-age-aware startup price checks.
- Changed trader restock reminders from modal message boxes to a left-side non-focus, mouse-through overlay so reminders do not interrupt gameplay.
- Added a configurable reminder visibility hotkey, defaulting to `F7`, to hide or show persistent restock reminder overlays.
- Changed trader countdown OCR so `F8` immediately schedules reminders for checked traders instead of requiring a separate `F10` hotkey.
- Added left-side floating operation feedback for trader countdown OCR and hideout scans so hotkey actions report what was recorded.
- Changed price-cache and historical-price refreshes to prefer tarkov.dev's static JSON API, preserve existing caches on failure, and ask before trying GraphQL as a fallback.

## 0.5.0 - 2026-06-27

- Added an initial hideout upgrade tracking panel with full-screen hideout OCR capture.
- Added a configurable hideout scan hotkey, defaulting to `F6`.
- Added local hideout requirement caching from tarkov.dev and local progress records per scanned facility.
- Added current-upgrade and max-level hideout demand lines to item price results when a matched item is needed by recorded facilities.
- Added quantity-sequence alignment so noisy full-screen OCR can skip unrelated `x/y` values before recording hideout item counts.
- Changed hideout recognition to locate the right-side upgrade panel by its white border, then OCR targeted title, requirement, and quantity crops.
- Added game-order overrides for hideout levels where tarkov.dev API order does not match the in-game material row.
- Added a system tray mode with a close confirmation dialog: minimize to tray, exit, or cancel.
- Added the first app icon and wired it into the main window, tray icon, and PyInstaller executable.
- Added item-name autocomplete for manual price lookup, showing Chinese item names with colored category tags.
- Changed all OCR paths to use RapidOCR v5 and removed the old Tesseract runtime, settings, packaging, and documentation.
- Removed unused legacy OCR helpers for full-screen inventory detection and automatic PvE/PvP detection.
- Changed price result cards to prioritize total best/reference value, show per-slot value underneath, and request historical price details for high-volatility items.

## 0.4.2 - 2026-06-22

- Changed the default in-raid item price lookup hotkey to `Q`.
- Added RapidOCR PP-OCRv5 recognition as an experimental selectable OCR engine.
- Improved OCR matching by prioritizing full official item-name matches across all OCR candidates.
- Added simplified/traditional Chinese character normalization for OCR drift such as `貓` -> `猫`, `黃` -> `黄`, `製` -> `制`, `屍` -> `尸`, and `掛` -> `挂`.
- Updated release README documentation for clearer installation, usage, troubleshooting, and safety notes.

## 0.4.1 - 2026-06-21

- Added firearm detection for price results so guns use a camouflage-green marker instead of misleading value-per-slot tiers.
- Added `types` to refreshed tarkov.dev item cache data and fallback firearm classification for existing caches.
- Changed firearm overlay text to indicate that weapon value should be evaluated by attachments.
- Added explicit shutdown cleanup for global hotkeys, reminder timers, overlay toasts, and background workers.
- Fixed OCR variant selection so Chinese tooltip names like Ibuprofen are not overridden by an earlier bad Latin-letter OCR result.

## 0.4.0 - 2026-06-21

- Added a sidebar layout with separate panels for in-raid price lookup, trader restock reminders, and data tools.
- Added Chinese-first item display with an English fallback and a Settings language selector.
- Added item size fields to the price cache model and value-per-slot calculation when refreshed data includes dimensions.
- Updated default value tiers for EFT's long-tail per-slot prices, including a rainbow accent for 500k+ per slot.
- Restyled the price overlay as independent translucent result cards with tier-colored accents.
- Changed the visible log to show only lookup results and rejection/no-match events while writing full diagnostics to `debug/latest_run.log`.
- Kept the v0.3.0 tooltip cursor-gap fix and scaled it by capture height for different resolutions.

## 0.3.0 - 2026-06-21

- Added a main-window PvE/PvP price mode dropdown, defaulting to PvE.
- Removed automatic PvE/PvP OCR detection from item price lookup.
- Changed repeated hover item lookups to reuse the calibrated Tarkov capture size and avoid full-screen capture unless the resolution changes.
- Added a short inventory-tab detection cache so repeated item lookups avoid unnecessary tab OCR.
- Changed the price overlay to show up to three independent result toasts, newest on top, with timed fade-out.
- Improved item OCR cleanup for noisy mixed Chinese/English tooltip text and added Iskra localized aliases.
- Tightened tooltip border detection to reject empty inventory-grid regions mistaken for item-name boxes.
- Improved tooltip selection near currency stacks so adjacent item labels are not preferred over the real tooltip.
- Scaled the tooltip cursor-gap heuristic by capture height so different resolutions keep the same relative spacing.
- Removed unused PvE/PvP OCR settings from the Settings dialog.

## 0.2.0 - 2026-06-21

- Added hover-tooltip item recognition flow for EFT item price lookup.
- Added PvP/PvE-separated local price caches.
- Added Chinese localized item-name support and alias lookup.
- Added cached capture region reuse so repeated item lookups avoid full-screen capture for mode/tab checks.
- Added exact-name and repeated-query fast paths for local item lookup.
- Added PyInstaller portable build configuration.
