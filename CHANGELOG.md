# Changelog

## 0.3.0 - 2026-06-21

- Added a main-window PvE/PvP price mode dropdown, defaulting to PvE.
- Removed automatic PvE/PvP OCR detection from item price lookup.
- Changed repeated hover item lookups to reuse the calibrated Tarkov capture size and avoid full-screen capture unless the resolution changes.
- Added a short inventory-tab detection cache so repeated item lookups avoid unnecessary tab OCR.
- Changed the price overlay to show up to three independent result toasts, newest on top, with timed fade-out.
- Improved item OCR cleanup for noisy mixed Chinese/English tooltip text and added Iskra localized aliases.
- Tightened tooltip border detection to reject empty inventory-grid regions mistaken for item-name boxes.
- Removed unused PvE/PvP OCR settings from the Settings dialog.

## 0.2.0 - 2026-06-21

- Added hover-tooltip item recognition flow for EFT item price lookup.
- Added PvP/PvE-separated local price caches.
- Added Chinese localized item-name support and alias lookup.
- Added cached capture region reuse so repeated item lookups avoid full-screen capture for mode/tab checks.
- Added exact-name and repeated-query fast paths for local item lookup.
- Added PyInstaller portable build configuration.
