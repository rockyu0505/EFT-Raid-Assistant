# Tarkov Raid Assistant

MVP Windows desktop app for Escape from Tarkov trader restock reminders and item price lookup.

The app does not automate gameplay. It only captures a screenshot when you ask it to, OCRs visible text, lets you manually correct OCR output, schedules local popup/sound reminders, and looks up item prices from the public tarkov.dev GraphQL API.

## Setup

### Conda Setup

1. Install Miniconda or Anaconda on Windows 11.
2. Open Anaconda Prompt, then run:

```powershell
cd "C:\Users\zetia\Documents\EFT Reminder"
conda env create -f environment.yml
conda activate eft-raid-assistant
python main.py
```

If you later change `environment.yml`, update the existing environment:

```powershell
conda env update -f environment.yml --prune
```

### Python venv Setup

1. Install Python 3.11 or newer on Windows 11.
2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Install Tesseract OCR for Windows:

Download an installer from the UB Mannheim builds:

https://github.com/UB-Mannheim/tesseract/wiki

The usual executable path is:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

Paste that path into the app's `Tesseract path` field if OCR fails to find it automatically.

## Run

```powershell
python main.py
```

The main window keeps daily controls visible. Configuration lives under
`设置 > 打开设置`.

## Basic Usage

### Trader Reminders

1. Open the Tarkov trader screen.
2. Use borderless windowed mode when possible. Exclusive fullscreen can make screenshots, hotkeys, or popups unreliable.
3. Press `F8` or click `识别倒计时`.
4. Check the editable `Countdown / manual fix` fields. OCR is only a starting point in this MVP.
5. Select the traders you want to watch.
6. Press `F10` or click `设置选中提醒`.
7. Leave the app running. It checks reminders once per second.

### Item Price Lookup

1. Move the mouse onto an item and wait for Tarkov to show the full hover name near the cursor.
2. After the name box is visible, press the item price hotkey, default `F9`, while Tarkov is still the foreground window.
3. The app first checks that the current foreground window looks like Tarkov. If another app, Alt-Tab, or the assistant window is in front, it cancels without taking a screenshot.
4. The app immediately captures a larger tooltip search area near the cursor, locates the tooltip border, crops the final name box, OCRs the item name, then looks it up from the local price cache.
5. If OCR is wrong, correct the editable item name field manually and click `查询手动名称`.
6. If enabled in settings, the app OCR-checks that an inventory/details UI is open.
7. Keep `显示置顶价格浮窗` enabled to show the result in a small overlay near the top-right of the primary monitor.

For normal use, prefer the hotkey while the game remains focused. Clicking `识别物品并查价` in the app is mainly for debugging; if your mouse is on the app window, hover recognition will capture the app instead of the game.

The hover tooltip crop can be tuned in `设置 > 打开设置 > 截图`:

- `物品识别方式`: default is `鼠标悬停提示`; `固定物品名 ROI` keeps the older fixed-crop behavior.
- `悬停等待毫秒`: optional extra wait before capture. Keep it at `0` if you press the hotkey after the game name box is already visible.
- `悬停搜索边距`: large search area around the cursor, ordered left/right/up/down. The default searches farther upward so long hover names and container names are less likely to be clipped.
- `名称框留白`: padding added after OCR finds the tooltip text bounds.
- `悬停提示偏移`: crop start offset from the cursor.
- `悬停提示尺寸`: crop width and height.
- `装备页签 ROI`: crop of the top-left active `装备` tab. If this crop contains the active equipment tab, the app treats the inventory page as open.

## Chinese Item Names

tarkov.dev currently returns item IDs, English names, normalized names, and prices, but not Chinese item names. For Chinese game UI OCR, this app uses a local alias table:

```text
data/item_aliases_zh.json
```

Each real entry maps a Chinese in-game name or common nickname to a tarkov.dev `id`, `normalizedName`, English full name, or English short name:

```json
{
  "显卡": "graphics-card",
  "LEDX皮肤透照仪": "ledx-skin-transilluminator"
}
```

After editing the file, use `数据 > 重新加载中文别名` without restarting the app. Use `数据 > 打开中文别名文件` to open the file from the app.

For Chinese OCR, set `物品 OCR 语言` to `chi_sim+eng` in settings. If Tesseract does not have the Chinese traineddata installed, the app falls back to the default language, but Chinese item recognition will be much worse. In that case, install or copy `chi_sim.traineddata` into your Tesseract `tessdata` folder.

For the conda environment, both Chinese and English traineddata should be in:

```text
%CONDA_PREFIX%\Library\share\tessdata
```

Check what is installed:

```powershell
dir "%CONDA_PREFIX%\Library\share\tessdata\*.traineddata"
```

If `eng.traineddata` is missing, download it:

```powershell
curl.exe -L "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata" -o "%CONDA_PREFIX%\Library\share\tessdata\eng.traineddata"
```

Then verify:

```powershell
set TESSDATA_PREFIX=%CONDA_PREFIX%\Library\share\tessdata
tesseract --list-langs
```

## Price Cache

On startup, the app requests the full item list from the public tarkov.dev GraphQL API for both PvP and PvE prices and stores them in:

```text
cache/tarkov_items_regular.json
cache/tarkov_items_pve.json
```

Raid-time lookup uses the local cache instead of making a network request per item. The app OCRs the bottom-left game mode marker (`PvE`/`PvP`) from the full screenshot before lookup and chooses the matching cache. Use
`数据 > 刷新价格缓存` to refresh it manually.

If the bottom-left mode marker is not detected, the fallback mode comes from `设置 > 打开设置 > 价格 > 识别失败默认价格模式`.

## Debug Files

After every capture, the app writes:

- `debug/last_full_screenshot.png`
- `debug/last_timer_strip.png`
- `debug/last_item_hover_search.png`
- `debug/last_item_name.png`
- `debug/last_inventory_tab.png`
- `debug/last_game_mode.png`

If OCR is shifted or wrong, open the debug crop and adjust the ROI base fields:

```text
x0, y0, x1, y1
default: 0, 150, 1500, 240
```

The ROI is expressed in base coordinates for a `2048x1152` reference image and is scaled to the captured or manually overridden resolution.

The fixed item price ROI uses the same base-coordinate system:

```text
default: 670, 120, 1420, 260
```

Open `debug/last_item_hover_search.png` after a lookup to confirm the broad search area contains the tooltip. Then check `debug/last_item_name.png`; it should contain only the dark tooltip name box. The app first looks for the tooltip's light rectangular border, then falls back to OCR text clustering if the border cannot be found. Tune the hover search margins or name-box padding if either image is off.

If item lookup says the equipment page was not detected, open `debug/last_inventory_tab.png`. It should contain the active top-left `装备` tab. If it is shifted, adjust `装备页签 ROI` in settings.

If item lookup uses the wrong PvE/PvP price mode, open `debug/last_game_mode.png`. It should contain the bottom-left version strip with the `PvE` or `PvP` marker. If it is shifted, adjust `模式标记 ROI` in settings.

## Troubleshooting

- OCR detects wrong times: correct the timer fields manually, then schedule. Try changing the ROI fields and capture again.
- Debug crop is shifted: use the manual resolution override or adjust ROI values.
- Hotkey does not work: open `设置 > 打开设置`, try a simpler hotkey like `F8`, save, and make sure the app has permission to listen for global hotkeys.
- Chinese item lookup fails: add or correct the item in `data/item_aliases_zh.json`, then use `数据 > 重新加载中文别名`.
- Price lookup fails: use `数据 > 刷新价格缓存` while online, then try a manual item name.
- Inventory detection is too strict: first tune `装备页签 ROI`; if needed, open `设置 > 打开设置 > 价格` and disable `查价前先检测背包/详情界面`.
- Price lookup cancels before screenshot: Tarkov was not the foreground window. Click back into Tarkov, wait for the hover name box, then press the hotkey. If your Tarkov window title or process is not detected correctly, open `设置 > 打开设置 > 价格` and disable `截图前要求 Tarkov 是前台窗口`.
- Wrong item matched: correct the `Item name` manually, or include more of the detail-window item title in the item ROI.
- Fullscreen screenshot is black: use borderless windowed mode.
- Multi-monitor capture chooses the wrong screen: choose `Primary monitor` or move the cursor to the correct monitor and choose `Monitor under cursor`.
- Tarkov window mode does not work: install `pywin32`, or use `Auto`, `Monitor under cursor`, or `Primary monitor`.

## Project Layout

```text
main.py
app/
  gui.py
  capture.py
  item_ocr.py
  ocr.py
  prices.py
  reminders.py
  hotkeys.py
  config.py
  models.py
cache/
debug/
assets/
environment.yml
requirements.txt
README.md
```
