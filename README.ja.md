[简体中文](README.zh-CN.md) | [English](README.en.md) | [日本語](README.ja.md)

# astrbot_plugin_getBilibili

AstrBot プラグイン：グループ内の Bilibili 動画を自動で解析・ダウンロードし、グループチャットに送信します。

- **規制対策万全**：412 でブロックされやすい `yt-dlp` を捨て、`bilibili-api` で直リンクを取得。匿名クレデンシャル処理を内蔵。
- **マルチノードフェイルオーバー**：Bilibili CDN の予備直リンクを自動抽出し、567 / 403 など単一ノードの拒否時にはシームレスに切り替えて再試行します。
- **的確なトリガー**：「@bot」または「bot 自身が送信したメッセージ」内の Bilibili リンクのみに反応し、グループチャットの邪魔をしません。
- **モジュール設計**：コアロジックは `core/` ディレクトリに分割され、データ構造（`models.py`）も明確で、保守・拡張が容易です。
- **完全な保護機能**：レート制限、1日あたりの上限、同時実行制限、グループホワイトリスト、ファイルサイズ／画質制限、一時ファイルの自動削除。
- **WebUI 設定**：すべてのパラメータは AstrBot のプラグイン設定パネルから調整可能。コード変更は不要です。

---

## 📦 ディレクトリ構成

    astrbot_plugin_getBilibili/
    ├── main.py                 # プラグイン入口：イベント監視、トリガー判定、メッセージ送信
    ├── _conf_schema.json       # WebUI 設定定義
    ├── metadata.yaml           # プラグインメタ情報
    ├── README.md               # 本ファイル
    ├── core/
    │   ├── __init__.py
    │   ├── models.py           # データモデル：MediaStream / ParsedVideo / PreparedFile
    │   ├── downloader.py       # ダウンロードコア：bilibili-api ラッパー＋マルチノード再試行
    │   └── rate_limiter.py     # レート制限：クールダウン＋1日あたりの上限
    ├── utils/
    │   ├── __init__.py
    │   └── logger.py           # ログ補助
    └── temp/                   # 実行時に自動生成、一時動画を保存

---

## 🚀 インストール手順

### 1. プラグインの配置

`astrbot_plugin_getBilibili` フォルダ全体を AstrBot のプラグインディレクトリに配置します：

    AstrBot/data/plugins/astrbot_plugin_getBilibili/

### 2. Python 依存パッケージのインストール

本プラグインは `bilibili-api-python` と `aiohttp` に依存しています。AstrBot の実行環境で次を実行してください：

    pip install -U bilibili-api-python aiohttp

> **注意**：Bilibili の API は頻繁に更新されるため、`bilibili-api-python` を定期的にアップグレードすることをおすすめします：
> `pip install -U bilibili-api-python`

### 3. FFmpeg のインストール（必須）

Bilibili は DASH 形式（映像と音声が分離）を採用しているため、ダウンロード後に `ffmpeg` で**再エンコードなしの結合**を行う必要があります。未インストールの場合、`FileNotFoundError: 'ffmpeg'` が発生します。

- **Windows**: gyan.dev/ffmpeg/builds/ から release ビルドをダウンロードし、解凍後に `bin` ディレクトリをシステム環境変数 `PATH` に追加します。**追加後は必ず AstrBot を再起動してください。**
- **Linux (Debian/Ubuntu)**: `apt-get install -y ffmpeg`
- **macOS**: `brew install ffmpeg`

インストール後、ターミナルで `ffmpeg -version` を実行し、何か出力されれば成功です。

### 4. プラグインの再読み込み

AstrBot WebUI のプラグイン管理ページで「再読み込み」をクリックするか、AstrBot を再起動します。ログに読み込み成功が表示され、ERRO がなければ使用可能です。

---

## ⚙️ 設定説明

すべての設定項目は AstrBot WebUI → プラグイン → `bili_downloader` → 設定 から変更できます。

### 基本設定

- `enabled` (bool): デフォルト `true`。プラグインのマスタースイッチ。
- `bot_self_trigger` (bool): デフォルト `true`。bot 自身（ログイン中の QQ アカウント）が送信したメッセージでもトリガーするか。
- `cleanup_temp_on_start` (bool): デフォルト `true`。起動時に `temp/` 内の残存一時ファイルを削除します。

### トリガーと制限

- `group_whitelist` (list): デフォルト `[]`。グループホワイトリスト（グループ ID の文字列リスト）。空 = すべてのグループで有効。
- `per_user_cooldown` (int): デフォルト `30`。同一ユーザーの連続トリガー間の最小間隔（秒）。`0` = 無制限。
- `per_user_daily_limit` (int): デフォルト `10`。1ユーザーあたりの1日のダウンロード回数上限。`0` = 無制限。
- `max_concurrent` (int): デフォルト `2`。同時ダウンロードタスクの上限。

### ダウンロード制限

- `max_filesize_mb` (int): デフォルト `100`。最大ファイルサイズ（MB）。結合後は 10% の余裕を許容。QQ では `50` 以下を推奨。
- `max_height` (int): デフォルト `720`。最大解像度の高さ（px）。`480` / `720` / `1080` を推奨。

### 詳細ネットワーク設定

- `user_agent` (string): ブラウザを偽装する User-Agent。
- `proxy_url` (string): デフォルト `""`。ダウンロード用プロキシ、例：`http://127.0.0.1:7890`。空 = 直接接続。海外 IP や頻繁に拒否される場合に設定を推奨。

---

## 🎯 使い方

### トリガー条件

以下の**いずれか**を満たし、かつメッセージに Bilibili リンクが含まれる場合にトリガーします：

1. 他のユーザーが bot を @ して Bilibili リンクを送信：
   `@yourbot https://b23.tv/Rzkw6XA`
2. bot 自身（ログイン中の QQ アカウント）が Bilibili リンクを送信（`bot_self_trigger: true` が必要）：
   `https://www.bilibili.com/video/BV1xx411c7mD`

> **プライベートチャット**または **@bot** の場合のみトリガーします。通常のグループチャットでリンクを貼ってもトリガーされず、迷惑になりません。

### 対応リンク形式

- 短縮リンク：`https://b23.tv/xxxxxxx`
- 通常リンク：`https://www.bilibili.com/video/BVxxxxxxxxx`
- パラメータ付きリンク：`https://www.bilibili.com/video/BVxxxxxxxxx?p=2`

### 処理フロー

1. リンクを検出 → 「📥 Bilibili 動画リンクを検出しました。解析・ダウンロード中...」と返信
2. バックグラウンドで解析開始。複数の画質がある場合、設定の `max_height` に基づいて最高画質を自動選択。
3. ダウンロード開始。**プライマリノードが拒否（HTTP 567）した場合、コンソールに警告を出力し、予備ノードを自動で試行します。**
4. ダウンロード完了 → `ffmpeg` で音声と映像を高速結合。
5. 動画を送信＋「✨ 動画の解析に成功しました（サイズ: xx.xMB）」
6. 成功・失敗にかかわらず、一時ファイルは即座に削除。

---

## 🛠️ トラブルシューティング

### エラー：`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**原因**：システム環境変数に `ffmpeg` が見つかりません。
**解決策**：上記のインストール手順を参照し、`ffmpeg` をシステムの `PATH` に追加してください。AstrBot（またはそれを実行しているターミナル）を再起動して反映させてください。

### エラー：`HTTP 567` または `HTTP 403`（ダウンロード失敗）

**原因**：Bilibili のいずれかの CDN ノード（例：`upos-sz-mirrorcosov.bilivideo.com`）があなたの IP からのリクエストを拒否しました。
**解決策**：現行コードには**予備ノードへの自動再試行**が組み込まれています。ログに `节点被拒或失效，尝试下一个备用节点...` が表示された後に成功するのは正常な動作です。すべてのノードが失敗する場合は、設定で `proxy_url` を指定してください（出口 IP の変更）。

### エラー：`'list' object has no attribute 'chain'`

**原因**：AstrBot のバージョン互換性の問題。`event.send()` は通常のリストではなく `MessageEventResult` を要求します。
**解決策**：修正済みです（`event.chain_result()` でリストをラップ）。最新版の `main.py` を使用していることを確認してください。

### 動画の送信に失敗する／表示されない

- **ファイルが大きすぎる**：`max_filesize_mb` を確認してください。QQ グループのファイルアップロードには通常サイズ制限があります（通常グループで約 100MB、OneBot の実装に依存）。`50` 以下に設定することを推奨します。
- **画質が高すぎる**：`max_height` を下げる（例：`480`）と、ファイルサイズを大幅に削減できます。

---

## ❓ よくある質問

### Q: 本当にログインは一切不要ですか？

**はい。** 本プラグインは `bilibili-api-python` を使用しており、匿名 `buvid` の取得と WBI 署名をバックグラウンドで自動処理します。アカウントの Cookie を提供する必要はなく、アカウント停止のリスクもありません。

### Q: なぜ @bot しないとトリガーされないのですか？

通常のグループチャットに現れる Bilibili リンクが誤ってダウンロードされるのを防ぎ、帯域とサーバーリソースを節約するためです。特定のグループで有効にしたい場合は、`group_whitelist` にグループ ID を追加してください。

### Q: 分P動画には対応していますか？

はい。リンクに `?p=2` パラメータが含まれている場合、該当する分Pを解析します。

### Q: 番組（アニメ）／ライブ配信／動的投稿には対応していますか？

現在のバージョンは `bilibili.com/video/BVxxx` と `b23.tv/xxx` の2種類のリンクのみにマッチします。番組、ライブ配信、動的投稿には未対応です。

### Q: 一時ファイルはどこにありますか？残留しますか？

一時ファイルはプラグインディレクトリ内の `temp/` に保存され、ダウンロードごとに独立したサブディレクトリ（`temp/bili_xxxxx/`）を使用し、送信完了後すぐに削除されます。起動時に `cleanup_temp_on_start: true` の場合、過去の残留ファイルもすべて削除されます。

---

## 📄 バージョン

- **現在のバージョン**：2.2.0
- **AstrBot 互換性**：>= 4.29.0
- **作者**：niniko

---

## 📜 ライセンス

本プラグインは個人の学習・私的利用を目的としています。使用によって生じたいかなる結果も利用者自身の責任となります。Bilibili の利用規約およびお住まいの地域の法令を遵守し、商業利用や大規模なクローリングには使用しないでください。