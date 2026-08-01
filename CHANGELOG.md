# Changelog

## 0.6.0 - Unreleased

- Added a first-run feature setup dialog and Settings feature toggles so users can enable only the panels they need; changes take effect after restart.
- Changed feature toggles to be hard module gates: disabled modules do not create their runtime managers, register hotkeys, start background refreshes, or apply display filters.
- Changed Settings to open on the hotkey tab by default and moved low-frequency capture ROI/manual resolution controls into a collapsed advanced capture section.
- Added a dark, translucent upper-right in-raid control panel (`F9`) for live price mode, display language, overlay timing, panel opacity, and Gamma adjustment.
- Added a lower-left raid log (`F10`) that shows without proactively taking focus, then supports click, wheel/scrollbar history navigation, and title-bar dragging.
- Added an optional offline recipe-tracking module using tarkov.dev's game-handbook category hierarchy, with a category browser and product → concrete recipe → per-material rows.
- Added a tracked-recipe overview for unified untracking, multi-selection deletion, clearing, and recipe-notice accent-color customization.
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
- Changed the visible log into a persistent main-window section shared by all feature panels, with automatic scrolling to the newest entry.
- Hid foreground-window rejection messages from the visible log to avoid spam while users alt-tab or chat outside the game.
- Added a performance settings tab with visible-log line limits, background-worker concurrency limits, worker-finished memory cleanup, periodic idle cleanup, and a default performance-mode skip for automatic price-cache refreshes.
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
