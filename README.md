# EFT Raid Assistant

一个面向中文玩家的 Escape from Tarkov 局内辅助工具。它专注于截图、OCR、本地查价和提醒，不会点击鼠标、移动鼠标、读取游戏内存、注入游戏进程或自动化游戏操作。

当前版本：`0.5.0`

## 功能概览

- 局内物品查价：鼠标悬停物品，等待 Tarkov 显示名称 tooltip 后按热键查询价格。
- 中文优先显示：默认显示官方中文物品名，可在设置中切换为英文。
- PvE / PvP 手动选择：默认 PvE，避免额外 OCR 判断和误判。
- 价格缓存：启动时或手动刷新 tarkov.dev 数据，局内查询走本地缓存。
- 价值颜色：按单格价值显示白、绿、蓝、紫、金、红和彩色高价值提示。
- 枪械特殊标记：枪械用迷彩绿色提示，不按单格价值误导评估。
- 右上角浮窗：最多保留三条查价结果，定时淡出。
- 商人补货提醒：保留 OCR 倒计时和本地提醒功能，仍属于实验功能。

## 下载与运行

从 GitHub Release 下载压缩包后：

1. 完整解压整个 zip。
2. 进入解压后的文件夹。
3. 双击运行 `EFT Raid Assistant.exe`。

不要只复制或单独发送 exe。程序运行需要旁边的 `_internal`、`cache`、`data`、`assets` 等目录。

如果 Windows SmartScreen 提示未知发布者，这是未签名个人项目的正常现象。确认来源可信后，可以点击“更多信息”并选择“仍要运行”。

## 默认热键

| 功能 | 默认热键 |
| --- | --- |
| 局内物品查价 | `Q` |
| 识别藏身处升级 | `F6` |
| 识别商人倒计时 | `F8` |
| 设置选中商人提醒 | `F10` |

所有热键都可以在 Settings 中修改。

## 局内查价流程

1. 打开 Tarkov 装备、背包或容器界面。
2. 把鼠标悬停到要查询的物品上。
3. 等游戏显示完整物品名称 tooltip。
4. 保持 Tarkov 为前台窗口，按 `Q`。
5. 程序会截取鼠标附近的小区域，定位 tooltip，OCR 物品名，并查询本地价格缓存。
6. 结果会显示在主界面日志和右上角浮窗中。

如果 OCR 结果明显不对，可以在主界面的手动输入框中输入物品名重新查询。

## 价格和颜色

普通物品默认按单格价值分级：

| 单格价值 | 颜色 |
| --- | --- |
| 0 - 1 万 | 白色 |
| 1 - 2 万 | 绿色 |
| 2 - 5 万 | 蓝色 |
| 5 - 10 万 | 紫色 |
| 10 - 25 万 | 金色 |
| 25 - 50 万 | 红色 |
| 50 万以上 | 彩色渐变 |

枪械价值通常来自配件，而不是下机匣本身的单格价值，所以枪械使用独立的迷彩绿色提示，由玩家自行评估配件价值。

## OCR 引擎

当前统一使用 RapidOCR v5，使用 `ch_PP-OCRv5_rec_mobile` 识别局内物品名、倒计时和藏身处升级信息。

0.5.0 统一使用 RapidOCR v5，并保留简繁字符归一化，用于处理 OCR 将 `猫` 识别为 `貓`、`黄` 识别为 `黃` 等情况。

## 数据来源

物品价格和基础数据来自公开的 tarkov.dev GraphQL API。

本地缓存文件位于：

```text
cache/tarkov_items_regular.json
cache/tarkov_items_pve.json
```

如果价格异常或数据过期，可以在 Data 面板中刷新价格缓存。

## 日志与调试

主界面只显示关键结果，例如：

- 查价成功
- 没有匹配物品
- Tarkov 不是前台窗口
- 当前界面不适合查价

完整运行日志保存在：

```text
debug/latest_run.log
```

最近一次截图和 OCR 调试图保存在 `debug` 目录。反馈 OCR 问题时，建议同时提供 `debug` 目录和 `debug/latest_run.log`。

## 安全边界

本工具只做以下事情：

- 截图
- OCR 识别
- 查询本地价格缓存
- 显示浮窗
- 本地提醒

本工具不会：

- 自动点击或移动鼠标
- 自动购买、出售或整理物品
- 读取游戏内存
- 注入游戏进程
- 修改游戏文件
- 与反作弊做任何交互

## 从源码运行

推荐 Windows 11 + Python 3.11。

### Conda

```powershell
cd "C:\Users\zetia\Documents\EFT Reminder"
conda env create -f environment.yml
conda activate eft-raid-assistant
python main.py
```

如果环境已经存在：

```powershell
conda env update -f environment.yml --prune
conda activate eft-raid-assistant
python main.py
```

### venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

源码运行只需要安装 `requirements.txt` 中列出的 Python 依赖。

## 打包

项目使用 PyInstaller：

```powershell
conda activate eft-raid-assistant
pyinstaller --clean --noconfirm "EFT Raid Assistant.spec"
```

构建产物位于：

```text
dist/EFT Raid Assistant/
```

发布时将整个目录压缩为 zip，而不是只分发 exe。

## 常见问题

### 按热键没有反应

确认程序正在运行，热键没有被其他软件占用。可以到 Settings 中换成其他按键。

### 查价提示不是 Tarkov 前台窗口

重新点击 Tarkov，让游戏成为前台窗口后再按查价热键。

### OCR 识别错物品

等待 tooltip 完整显示后再按热键。若仍然错误，请保留 `debug` 目录和 `debug/latest_run.log` 用于排查。

### 价格模式不对

在主界面手动选择 PvE 或 PvP。当前版本默认 PvE，不再依赖 OCR 自动判断模式。

### exe 无法单独运行

这是正常的。PyInstaller 包需要 exe 和 `_internal` 等目录一起存在。

## 项目结构

```text
main.py
app/
  gui.py
  capture.py
  item_ocr.py
  prices.py
  reminders.py
  hotkeys.py
  config.py
  models.py
data/
cache/
debug/
assets/
scripts/
EFT Raid Assistant.spec
README.md
CHANGELOG.md
VERSION
```

## License

本项目代码使用 MIT License，详见 [LICENSE](LICENSE)。

第三方依赖、OCR 模型、Qt/PySide6 运行库和 tarkov.dev 数据源仍遵循各自的上游许可证或服务条款，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
