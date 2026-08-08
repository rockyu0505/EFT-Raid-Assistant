EFT Raid Assistant portable EXE
===============================

How to run
----------
1. Extract the whole folder to a simple path, for example:
   D:\tkf\EFT-Raid-Assistant

2. Double-click:
   EFT Raid Assistant.exe

No Miniconda, Python, or separate OCR installation is required for this
portable build.

Notes
-----
- Keep the _internal folder next to the exe. Do not move the exe alone.
- Keep EFT Raid Assistant Updater.exe next to the main exe. Packaged builds use
  it after restart to apply verified updates while preserving user data.
- Starting with 0.8.0, packaged releases check for updates at startup. New
  versions are downloaded and installed only after explicit confirmation.
- If Windows SmartScreen warns about an unknown app, choose "More info" and
  "Run anyway" if you trust this release.
- The app only captures screenshots and runs OCR. It does not click, move the
  mouse, read game memory, or interact with the game process.
- Price lookup and tracked recipes support PvE, PvP, and tarkov.dev's seasonal
  PvP mode as separate local datasets.
- If OCR or item lookup is wrong, send the debug folder and the app log text
  back to the developer.
