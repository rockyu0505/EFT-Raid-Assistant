EFT Raid Assistant test package
================================

Quick start
-----------
1. Install Miniconda or Anaconda if conda is not installed.
   Recommended Miniconda page:
   https://docs.conda.io/en/latest/miniconda.html

2. Double-click install_env.bat.
   This creates or updates the conda environment named:
   eft-raid-assistant

3. Double-click start_eft_raid_assistant.bat.

4. In Tarkov, wait until the item hover name box appears, then press N.

What the installer does
-----------------------
- Creates or updates the conda environment from environment.yml.
- Installs Python dependencies.
- Installs RapidOCR and ONNX Runtime Python dependencies.

Useful hotkeys
--------------
- N: item price lookup
- F8: trader restock timer OCR
- F10: schedule selected reminders

Notes
-----
- The app only captures screenshots and runs OCR. It does not click, move the mouse,
  read game memory, or interact with the game process.
- If item lookup does nothing, make sure the Tarkov window is the foreground window.
- If OCR is bad, send the files under debug/ together with the app log text.
- Price caches are included for testing. Use Data > Refresh price cache in the app
  if current prices look stale.
