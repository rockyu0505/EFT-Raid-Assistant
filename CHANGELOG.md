# Changelog

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
