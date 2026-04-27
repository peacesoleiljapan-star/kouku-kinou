# Synology + Tailscale 配置手順

この手順書は、Synology NAS 上で 口腔機能・栄養評価システム を動かし、Tailscale Serve で HTTPS 終端したい管理者向けです。DSM の独自ドメイン運用やリバースプロキシ設定は使いません。

## この構成でやること

1. Synology Container Manager でアプリを起動する
2. アプリのポートを NAS 自身の `127.0.0.1:8010` だけに公開する
3. Synology 上の Tailscale Serve で `https://diskstation.tail632bc4.ts.net/` を有効にする
4. 利用者には Tailscale 接続後の HTTPS URL だけを案内する

## 現在の tailnet 情報

1. device 名: `diskstation`
2. tailnet 名: `tail632bc4`
3. 現在のアプリ URL: `https://diskstation.tail632bc4.ts.net/`

## この構成でやらないこと

1. Synology 独自ドメインの取得
2. DSM リバースプロキシ設定
3. ルーターでのポート開放
4. Tailscale Funnel によるインターネット公開

Tailscale Serve は tailnet 内限定です。公開 URL を全世界へ出したい用途には向きません。

## このアプリの置き場所

Synology に置く主なものは次のとおりです。

1. `compose.yaml`: アプリ全体を起動する設定
2. `.env`: 認証モードや管理者パスワード
3. `server.py`: アプリ本体を配信するサーバー
4. `index.html`: 元の画面ソース
5. `data/records.db`: 記録データ。最重要ファイル

## 事前準備

Synology 側で次を確認します。

1. Container Manager が入っている
2. Tailscale が Synology に導入済みで、tailnet へ参加できている
3. 保存用フォルダを作れる
4. 管理者が 1 回だけ Tailscale CLI を実行できる

作るフォルダ例:

1. `docker/kouku-kinou`
2. `docker/kouku-kinou/data`

このフォルダに以下を置きます。

1. `compose.yaml`
2. `.env`
3. `server.py`
4. `index.html`

## .env の確認

実運用前に次を確認してください。

1. `KOUKU_KINOU_AUTH_MODE=tailscale-or-password`
2. `KOUKU_KINOU_PASSWORD`: 管理者用の強いパスワードへ変更
3. `KOUKU_KINOU_SECURE_COOKIE=1`: このままでよい
4. `KOUKU_KINOU_ALLOWED_NETWORKS=`: 通常は空欄のままでよい
5. `KOUKU_KINOU_TRUST_PROXY=0`: 通常はこのままでよい

`tailscale-or-password` の意味:

1. 利用者が Tailscale の HTTPS URL から入れば自動認証される
2. うまくヘッダーが届かない時だけ、管理者用パスワードでも入れる

## Container Manager で起動する手順

1. DSM にログインします。
2. Container Manager を開きます。
3. 「プロジェクト」を開きます。
4. 「作成」を押します。
5. プロジェクト名を `kouku-kinou` にします。
6. フォルダに `docker/kouku-kinou` を指定します。
7. `compose.yaml` を読み込ませます。
8. 起動します。

起動後に確認すること:

1. コンテナ名が `kouku-kinou` になっている
2. ステータスが「実行中」になっている
3. healthcheck が有効な環境では `healthy` になっている
4. ログにエラーが出ていない

## ポート公開の考え方

`compose.yaml` は次のように loopback のみに bind しています。

```yaml
ports:
	- "127.0.0.1:8010:8010"
```

これにより、LAN から `http://NAS-IP:8010` で直接開かれにくくなり、Tailscale Serve を通す前提を守りやすくなります。

## Tailscale Serve を有効にする

この作業は管理者が 1 回だけ行います。DSM の画面操作だけではなく、Synology へ SSH 接続して実行します。

1. DSM の Control Panel > Terminal & SNMP で SSH を有効にします。
2. PC から Synology に SSH 接続します。
3. `sudo -i` で root 権限に切り替えます。
4. `tailscale status` で CLI が使えるか確認します。
5. `tailscale serve --bg 8010` を実行します。
6. `tailscale serve status` で公開 URL を確認します。

基本コマンド:

```powershell
ssh 管理者ユーザー名@NASのIP
sudo -i
tailscale status
tailscale serve --bg 8010
tailscale serve status
```

`tailscale` コマンドが見つからない場合は、Synology のパッケージ実体を直接呼びます。

```powershell
/var/packages/Tailscale/target/bin/tailscale status
/var/packages/Tailscale/target/bin/tailscale serve --bg 8010
/var/packages/Tailscale/target/bin/tailscale serve status
```

意味:

1. `tailscale serve --bg 8010`: `https://diskstation.tail632bc4.ts.net/` を `http://127.0.0.1:8010` へ転送
2. `tailscale serve status`: 現在の転送状態を確認

初回は HTTPS 有効化や同意のためにブラウザー画面が出ることがあります。表示された案内に従って許可してください。

もし以前の設定を消してやり直したい場合は次です。

```powershell
tailscale serve reset
tailscale serve --bg 8010
```

## 公開確認

次の順で確認します。

1. `tailscale serve status` に `proxy http://127.0.0.1:8010` が出る
2. `https://diskstation.tail632bc4.ts.net/api/health` が開ける
3. Tailscale 接続済みの PC からトップ画面が開ける
4. 同一利用者を保存するとき、生年月日未入力では保存できない
5. 同一利用者・同一評価日の再保存が上書き更新になる
6. 記録一覧の検索が使える
7. 別の端末で同じ記録が見える

## 利用者への配布

利用者には次の 2 つを渡します。

1. Tailscale の接続方法
2. アプリ URL または `TailscaleClientLauncher.cmd` 一式

Windows 利用者向けの簡易起動ツールは次の 3 ファイルです。

1. `TailscaleClientLauncher.cmd`
2. `TailscaleClientLauncher.ps1`
3. `TailscaleClientLauncher.settings.json`

`TailscaleClientLauncher.settings.json` の `appUrl` は `https://diskstation.tail632bc4.ts.net/` に設定済みです。URL を変更した時だけ、このファイルも合わせて更新してください。

タブレット利用者にはファイル一式を配るより、次の案内だけを渡すほうが簡単です。

1. App Store / Google Play で Tailscale を入れること
2. 管理者が指定した方法で Tailscale にサインインすること
3. `https://diskstation.tail632bc4.ts.net/` をブラウザーで開くこと

利用者向けの説明文は [TAILSCALE_TABLET_GUIDE_JA.md](TAILSCALE_TABLET_GUIDE_JA.md) をそのまま使えます。

短い配布メッセージは [TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md](TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.md)、紙で渡す案内は [TAILSCALE_TABLET_QR_SHEET_JA.md](TAILSCALE_TABLET_QR_SHEET_JA.md) を使えます。

## バックアップ

最重要なのは `data/records.db` です。これが記録本体です。

おすすめ:

1. 1 日 1 回バックアップ
2. 別フォルダへ世代管理
3. 週 1 回は復元テスト

## 更新手順

アプリを更新する流れは次のとおりです。

1. 先に `data/records.db` をバックアップ
2. 新しいファイルで `server.py` などを上書き
3. Container Manager でプロジェクトを再起動
4. 必要なら `tailscale serve status` を確認
5. `https://diskstation.tail632bc4.ts.net/` でログイン、保存、一覧表示、検索を確認
6. 同一利用者・同一評価日の更新挙動を 1 件だけ確認

## 困ったとき

### 1. URL を開いても画面が出ない

1. Container Manager でコンテナが起動しているか確認
2. `tailscale serve status` に設定が残っているか確認
3. `https://diskstation.tail632bc4.ts.net/api/health` を直接開いてみる

### 2. 「Tailscale 接続が必要です」と出る

1. 利用者 PC 側で Tailscale が未接続
2. `https://diskstation.tail632bc4.ts.net/` ではなく別 URL を開いている
3. Tailscale Serve を通らず直接アクセスしている

### 3. パスワード画面が出る

1. `tailscale-or-password` では予備入口として正常
2. Tailscale 接続が不完全な可能性があるので、まず helper で再接続確認

### 4. 保存できない

1. `data` フォルダの書き込み権限を確認
2. `records.db` が作成されているか確認
3. 生年月日が空でないか確認
4. コンテナログに SQLite エラーが出ていないか確認

## 最後に

この構成では、公開経路を Tailscale のみに絞るのが安全です。独自ドメインや DSM リバースプロキシを足さず、`https://diskstation.tail632bc4.ts.net/` を正式な入口として統一してください。