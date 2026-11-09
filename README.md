[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)
# astrbot_plugin_getBilibili

AstrBot 插件：自动解析并下载群内 B 站视频，发送到群聊。

- **无惧风控**：抛弃容易被 412 拦截的 `yt-dlp`，改用 `bilibili-api` 获取直链，内置匿名凭证处理。
- **多节点容灾**：自动提取 B 站 CDN 的备用直链，遇到 567 / 403 等单节点拒绝时，自动无缝切换重试。
- **精准触发**：仅响应「@bot」或「bot 自己发出的消息」中的 B 站链接，避免群聊打扰。
- **模块化设计**：核心逻辑拆分到 `core/` 目录，数据结构清晰（`models.py`），便于维护和扩展。
- **完整防护**：频率限制、每日上限、并发限制、群白名单、文件大小/画质限制、自动清理临时文件。
- **WebUI 配置**：所有参数可在 AstrBot 插件配置面板中调整，无需改代码。

---

## 📦 目录结构

    astrbot_plugin_getBilibili/
    ├── main.py                 # 插件入口：事件监听、触发判断、消息发送
    ├── _conf_schema.json       # WebUI 配置定义
    ├── metadata.yaml           # 插件元信息
    ├── README.md               # 本文件
    ├── core/
    │   ├── __init__.py
    │   ├── models.py           # 数据模型：MediaStream / ParsedVideo / PreparedFile
    │   ├── downloader.py       # 下载核心：封装 bilibili-api 与多节点重试机制
    │   └── rate_limiter.py     # 频率限制：冷却 + 每日上限
    ├── utils/
    │   ├── __init__.py
    │   └── logger.py           # 日志辅助
    └── temp/                   # 运行时自动创建，存放临时视频

---

## 🚀 安装步骤

### 1. 放置插件

将整个 `astrbot_plugin_getBilibili` 文件夹放到 AstrBot 插件目录下：

    AstrBot/data/plugins/astrbot_plugin_getBilibili/

### 2. 安装 Python 依赖

本插件依赖 `bilibili-api-python` 和 `aiohttp`。请在 AstrBot 的运行环境中执行：

    pip install -U bilibili-api-python aiohttp

> **注意**：B 站接口更新频繁，建议定期升级 `bilibili-api-python`：
> `pip install -U bilibili-api-python`

### 3. 安装 FFmpeg（必须）

由于 B 站采用 DASH 格式（视频和音频分离），插件下载完成后**必须**使用 `ffmpeg` 进行无重编码合并。如果未安装，下载时会报错 `FileNotFoundError: 'ffmpeg'`。

- **Windows**: 前往 gyan.dev/ffmpeg/builds/ 下载 release 包，解压后将 `bin` 目录添加到系统环境变量 `PATH` 中。**添加后必须重启 AstrBot**。
- **Linux (Debian/Ubuntu)**: 执行 `apt-get install -y ffmpeg`
- **macOS**: 执行 `brew install ffmpeg`

安装后，在终端输入 `ffmpeg -version` 有输出即代表成功。

### 4. 重载插件

在 AstrBot WebUI 的插件管理页面点击「重载」，或重启 AstrBot。如果日志显示加载成功且无 ERRO，即可开始使用。

---

## ⚙️ 配置说明

所有配置项均可在 AstrBot WebUI → 插件 → `bili_downloader` → 配置中修改。

### 基础配置

- `enabled` (bool): 默认 `true`。插件总开关。
- `bot_self_trigger` (bool): 默认 `true`。bot 自己发出的消息是否也触发（登入的 QQ 号自己发链接）。
- `cleanup_temp_on_start` (bool): 默认 `true`。启动时清理 `temp/` 中遗留的临时文件。

### 触发与限制

- `group_whitelist` (list): 默认 `[]`。群白名单（群号字符串列表）。留空 = 所有群生效。
- `per_user_cooldown` (int): 默认 `30`。同一用户两次触发的最小间隔（秒），`0` = 不限制。
- `per_user_daily_limit` (int): 默认 `10`。每用户每日下载次数上限，`0` = 不限制。
- `max_concurrent` (int): 默认 `2`。同时进行的下载任务上限。

### 下载限制

- `max_filesize_mb` (int): 默认 `100`。最大文件大小（MB），合并后允许 10% 余量。建议 QQ 端设为 50 或更低。
- `max_height` (int): 默认 `720`。最大分辨率高度（px）。建议 `480` / `720` / `1080`。

### 高级网络

- `user_agent` (string): 伪装浏览器 User-Agent。
- `proxy_url` (string): 默认 `""`。下载代理地址，如 `http://127.0.0.1:7890`。留空 = 直连。海外 IP 或频繁被拒建议配置。

---

## 🎯 使用方法

### 触发方式

满足以下**任一**条件，且消息中包含 B 站链接时触发：

1. 其他用户 @bot 并发送 B 站链接：
   `@你的bot https://b23.tv/Rzkw6XA`
2. bot 自己（登入的 QQ 号）发送 B 站链接（需 `bot_self_trigger: true`）：
   `https://www.bilibili.com/video/BV1xx411c7mD`

> 仅在**私聊**或**@bot**时触发，普通群聊中发链接不会触发，避免打扰。

### 支持的链接格式

- 短链：`https://b23.tv/xxxxxxx`
- 长链：`https://www.bilibili.com/video/BVxxxxxxxxx`
- 带参数长链：`https://www.bilibili.com/video/BVxxxxxxxxx?p=2`

### 处理流程

1. 检测到链接 → 回复「📥 检测到 B 站视频链接，正在解析并下载中...」
2. 后台开始解析，若有多个画质，按配置的 `max_height` 自动选择最高画质。
3. 开始下载。**如果主节点拒绝（HTTP 567），控制台会打印警告并自动尝试备用节点。**
4. 下载完成 → 调用 `ffmpeg` 极速合并音视频。
5. 发送视频 + 提示「✨ 视频解析成功（大小: xx.xMB）」
6. 无论成功与否，临时文件立即清理。

---

## 🛠️ 故障排查

### 报错：`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**原因**：系统环境变量中找不到 `ffmpeg`。
**解决**：请参考上文安装步骤，确保 `ffmpeg` 加入了系统 `PATH`。重启 AstrBot（或运行 AstrBot 的终端）使其生效。

### 报错：`HTTP 567` 或 `HTTP 403`（下载失败）

**原因**：B 站的某一个 CDN 节点（如 `upos-sz-mirrorcosov.bilivideo.com`）拒绝了你的 IP 请求。
**解决**：新版代码已经内置了**备用节点自动重试**。如果日志中看到 `节点被拒或失效，尝试下一个备用节点...` 并且最终成功，属于正常现象。如果所有节点全部失败，请在配置中填写 `proxy_url`（更换出口 IP）。

### 报错：`'list' object has no attribute 'chain'`

**原因**：AstrBot 版本兼容问题，`event.send()` 需要的是 `MessageEventResult` 而不是普通列表。
**解决**：代码已修复（使用 `event.chain_result()` 包装列表），请确保使用的是最新版 `main.py`。

### 视频发送失败 / 不显示

- **文件过大**：检查 `max_filesize_mb`。QQ 群文件上传通常有大小限制（普通群 100MB 左右，具体取决于 OneBot 实现），建议设为 `50` 或更低。
- **画质太高**：调低 `max_height`（如 `480`），可显著减小文件体积。

---

## ❓ 常见问题

### Q: 真的完全不需要登录吗？

**是的。** 新版底层采用 `bilibili-api-python`，它会在后台自动处理匿名 `buvid` 获取和 WBI 签名。你无需提供任何账号 Cookie，也无需担心封号风险。

### Q: 为什么非要 @bot 才触发？

避免群内普通聊天中出现的 B 站链接被误下载，节省带宽和服务器资源。如需在特定群放开，可在 `group_whitelist` 中添加群号。

### Q: 支持分 P 视频吗？

支持。链接中带 `?p=2` 参数时会解析对应分 P。

### Q: 支持番剧/直播/动态吗？

当前版本仅匹配 `bilibili.com/video/BVxxx` 和 `b23.tv/xxx` 两种链接。番剧、直播、动态暂不支持。

### Q: 临时文件在哪？会残留吗？

临时文件在插件目录下的 `temp/` 中，每次下载使用独立子目录（`temp/bili_xxxxx/`），发送完成后立即删除。启动时若 `cleanup_temp_on_start: true`，会清理所有历史残留。

---

## 📄 版本

- **当前版本**：2.2.0
- **AstrBot 兼容**：>= 4.29.0
- **作者**：niniko

---

## 📜 许可

本插件仅供个人学习与自用。使用产生的任何后果由使用者自行承担。请遵守 B 站服务条款及所在地区法律法规，勿用于商业用途或大规模抓取。
