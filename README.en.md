[简体中文](README.zh-CN.md) | [English](README.en.md) | [日本語](README.ja.md)

# astrbot_plugin_getBilibili

An AstrBot plugin that automatically parses and downloads Bilibili videos posted in group chats, then sends them back to the group.

- **Risk-control resistant**: Drops `yt-dlp` (easily blocked with HTTP 412) in favor of `bilibili-api` for direct links, with built-in anonymous credential handling.
- **Multi-node failover**: Automatically extracts backup Bilibili CDN direct links. When a single node rejects with 567 / 403, it seamlessly switches and retries.
- **Precise triggering**: Only reacts to Bilibili links in messages that "@bot" or are sent by the bot itself, avoiding group chat spam.
- **Modular design**: Core logic is split into the `core/` directory with clear data structures (`models.py`), making maintenance and extension easy.
- **Full protection**: Rate limiting, daily quota, concurrency limit, group whitelist, file size / quality limits, automatic temp file cleanup.
- **WebUI configuration**: All parameters can be adjusted in the AstrBot plugin config panel — no code changes required.

---

## 📦 Directory Structure

    astrbot_plugin_getBilibili/
    ├── main.py                 # Plugin entry: event listening, trigger detection, message sending
    ├── _conf_schema.json       # WebUI config definition
    ├── metadata.yaml           # Plugin metadata
    ├── README.md               # This file
    ├── core/
    │   ├── __init__.py
    │   ├── models.py           # Data models: MediaStream / ParsedVideo / PreparedFile
    │   ├── downloader.py       # Download core: bilibili-api wrapper + multi-node retry
    │   └── rate_limiter.py     # Rate limiting: cooldown + daily quota
    ├── utils/
    │   ├── __init__.py
    │   └── logger.py           # Logging helpers
    └── temp/                   # Auto-created at runtime, stores temporary videos

---

## 🚀 Installation

### 1. Place the Plugin

Put the entire `astrbot_plugin_getBilibili` folder into the AstrBot plugin directory:

    AstrBot/data/plugins/astrbot_plugin_getBilibili/

### 2. Install Python Dependencies

This plugin depends on `bilibili-api-python` and `aiohttp`. Run the following in the AstrBot runtime environment:

    pip install -U bilibili-api-python aiohttp

> **Note**: Bilibili's APIs change frequently. It is recommended to upgrade `bilibili-api-python` regularly:
> `pip install -U bilibili-api-python`

### 3. Install FFmpeg (Required)

Since Bilibili uses the DASH format (separate video and audio streams), the plugin **must** use `ffmpeg` to merge them without re-encoding after downloading. Without it, you will get `FileNotFoundError: 'ffmpeg'`.

- **Windows**: Download the release build from gyan.dev/ffmpeg/builds/, extract it, and add the `bin` directory to your system `PATH`. **You must restart AstrBot afterwards.**
- **Linux (Debian/Ubuntu)**: `apt-get install -y ffmpeg`
- **macOS**: `brew install ffmpeg`

After installation, run `ffmpeg -version` in a terminal. Any output means it works.

### 4. Reload the Plugin

Click "Reload" on the plugin management page in the AstrBot WebUI, or restart AstrBot. If the log shows successful loading with no ERRO, you are good to go.

---

## ⚙️ Configuration

All options can be modified in AstrBot WebUI → Plugins → `bili_downloader` → Config.

### Basic

- `enabled` (bool): Default `true`. Master switch for the plugin.
- `bot_self_trigger` (bool): Default `true`. Whether messages sent by the bot itself (the logged-in QQ account) also trigger downloads.
- `cleanup_temp_on_start` (bool): Default `true`. Clean up leftover temp files in `temp/` on startup.

### Trigger & Limits

- `group_whitelist` (list): Default `[]`. Group whitelist (list of group ID strings). Empty = all groups.
- `per_user_cooldown` (int): Default `30`. Minimum interval (seconds) between two triggers by the same user. `0` = unlimited.
- `per_user_daily_limit` (int): Default `10`. Max downloads per user per day. `0` = unlimited.
- `max_concurrent` (int): Default `2`. Max concurrent download tasks.

### Download Limits

- `max_filesize_mb` (int): Default `100`. Max file size (MB), with 10% allowance after merging. For QQ, `50` or lower is recommended.
- `max_height` (int): Default `720`. Max resolution height (px). `480` / `720` / `1080` recommended.

### Advanced Network

- `user_agent` (string): Spoofed browser User-Agent.
- `proxy_url` (string): Default `""`. Download proxy, e.g. `http://127.0.0.1:7890`. Empty = direct connection. Recommended for overseas IPs or frequent rejections.

---

## 🎯 Usage

### Triggering

The plugin triggers when **either** of the following is true and the message contains a Bilibili link:

1. Another user @-mentions the bot along with a Bilibili link:
   `@yourbot https://b23.tv/Rzkw6XA`
2. The bot itself (the logged-in QQ account) sends a Bilibili link (requires `bot_self_trigger: true`):
   `https://www.bilibili.com/video/BV1xx411c7mD`

> Triggers only in **private chats** or when **@-mentioned**. Posting links in normal group chats will not trigger anything, avoiding interruptions.

### Supported Link Formats

- Short link: `https://b23.tv/xxxxxxx`
- Long link: `https://www.bilibili.com/video/BVxxxxxxxxx`
- Long link with params: `https://www.bilibili.com/video/BVxxxxxxxxx?p=2`

### Processing Flow

1. Link detected → replies "📥 Bilibili video link detected, parsing and downloading..."
2. Parsing starts in the background. If multiple qualities exist, the highest one within `max_height` is selected automatically.
3. Download starts. **If the primary node rejects (HTTP 567), a warning is printed and backup nodes are tried automatically.**
4. Download complete → `ffmpeg` merges audio and video at maximum speed.
5. Video is sent + message "✨ Video parsed successfully (size: xx.xMB)"
6. Temporary files are cleaned up immediately, regardless of success.

---

## 🛠️ Troubleshooting

### Error: `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**Cause**: `ffmpeg` cannot be found in the system `PATH`.
**Solution**: Follow the installation steps above and make sure `ffmpeg` is added to your system `PATH`. Restart AstrBot (or the terminal running it) for it to take effect.

### Error: `HTTP 567` or `HTTP 403` (download failed)

**Cause**: One of Bilibili's CDN nodes (e.g. `upos-sz-mirrorcosov.bilivideo.com`) rejected your IP.
**Solution**: The current code includes **automatic backup-node retries**. Seeing `节点被拒或失效，尝试下一个备用节点...` in the log followed by success is normal. If all nodes fail, set `proxy_url` in the config (change the egress IP).

### Error: `'list' object has no attribute 'chain'`

**Cause**: AstrBot version compatibility issue — `event.send()` expects a `MessageEventResult` rather than a plain list.
**Solution**: This has been fixed (the list is wrapped with `event.chain_result()`). Make sure you are using the latest `main.py`.

### Video fails to send / does not appear

- **File too large**: Check `max_filesize_mb`. QQ group file uploads usually have size limits (~100MB for regular groups, depending on the OneBot implementation). Set it to `50` or lower.
- **Quality too high**: Lower `max_height` (e.g. `480`) to significantly reduce file size.

---

## ❓ FAQ

### Q: Is it really true that no login is needed?

**Yes.** The plugin uses `bilibili-api-python`, which automatically handles anonymous `buvid` acquisition and WBI signing in the background. You do not need to provide any account cookies, and there is no ban risk.

### Q: Why must I @bot to trigger it?

To prevent Bilibili links appearing in normal group chat from being downloaded unintentionally, saving bandwidth and server resources. To enable it for specific groups, add their group IDs to `group_whitelist`.

### Q: Are multi-part (分P) videos supported?

Yes. If the link contains a `?p=2` parameter, the corresponding part is parsed.

### Q: Are bangumi / live streams / dynamic posts supported?

The current version only matches `bilibili.com/video/BVxxx` and `b23.tv/xxx`. Bangumi, live streams, and dynamic posts are not supported yet.

### Q: Where are the temp files? Will they be left behind?

Temp files are stored in `temp/` under the plugin directory. Each download uses its own subdirectory (`temp/bili_xxxxx/`), which is deleted immediately after sending. On startup, if `cleanup_temp_on_start: true`, all leftovers are cleaned up.

---

## 📄 Version

- **Current version**: 2.2.0
- **AstrBot compatibility**: >= 4.29.0
- **Author**: niniko

---

## 📜 License

This plugin is intended for personal study and private use only. Any consequences arising from its use are the sole responsibility of the user. Please comply with Bilibili's Terms of Service and the laws and regulations of your region. Do not use it for commercial purposes or large-scale scraping.