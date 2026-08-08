# EFT Raid Assistant 开发与发布要求

## 自动更新兼容性是强制验收项

0.8.0 建立了自动更新基线。从此版本开始，自动更新兼容性是所有后续开发和发布的 Definition of Done 必须项，不是可选的发布便利功能。

任何影响版本号、便携 ZIP 结构、可执行文件或附件名称、更新助手流程、清单格式、下载源、安装目录或用户数据保留路径的修改，都必须在同一批改动中同步适配更新器、发布工具、文档和自动化测试。

0.8.0 之后的每次发布都必须满足以下全部要求：

1. `VERSION` 必须是有效且单调递增的语义版本，并与 Git 标签、ZIP 文件名、包内 `VERSION`、Release 标题和更新清单版本完全一致。
2. 必须使用 `scripts/package_release.py` 构建完整便携目录；不支持只发布主程序 exe。
3. `EFT Raid Assistant Updater.exe` 必须与主程序并列，ZIP 必须保留 `EFT Raid Assistant/` 根目录和完整 `_internal` 树。
4. 成功更新后必须保留 `config.json`、`cache`、`data`、`debug`、`.update-cache` 以及文档列出的其他便携用户数据。目录结构变化必须提供明确迁移和回滚测试。
5. GitHub Release 必须同时上传构建生成的 ZIP、`.sha256` 和 `update-manifest.json`。清单内的大小、哈希、版本、文件名、发布页和 HTTPS 下载地址必须与实际附件一致。
6. 镜像只能通过清单增加且必须使用 HTTPS。除非后续迁移明确保持已安装客户端兼容，否则 GitHub 必须保留为最终回退源。
7. 发布前必须通过完整单元测试、源码 GUI smoke、包内程序 smoke、ZIP 结构校验、下载校验、安装替换、用户数据保留和失败回滚测试。
8. 发布后必须确认 `releases/latest/download/update-manifest.json` 和清单中的每个附件地址均可访问；当前正式包手动检查更新时必须显示已是最新版。
9. 修改清单 schema 时，必须让已安装的旧客户端仍可读取，或在迁移期间继续提供兼容的旧格式清单。破坏已有更新发现流程属于发布阻断问题。

在以上清单全部通过前，不得将版本标记为发布完成。无法安全跨越自动更新边界的功能必须保持未发布状态，直到具备兼容迁移方案。

## 发布命令

使用项目环境执行可重复发布脚本：

```powershell
C:\Users\zetia\miniconda3\envs\eft-raid-assistant\python.exe scripts\package_release.py
```

随后将 `release/` 中生成的下列文件上传到匹配版本的 GitHub Release：

- `EFT-Raid-Assistant-<version>-win64.zip`
- `EFT-Raid-Assistant-<version>-win64.zip.sha256`
- `update-manifest.json`
