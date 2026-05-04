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
3. `Dockerfile`: Container Manager で build するときに使う定義
4. `assets/`: HTML 資料と画面内参照で使う画像類
5. `server.py`: アプリ本体を配信するサーバー
6. `index.html`: 元の画面ソース
7. `README.html` などの配布資料: ヘルプと配布物で使う HTML / PDF
8. `data/records.db`: 記録データと共有設定。最重要ファイル

## 事前準備

Synology 側で次を確認します。

1. Container Manager が入っている
2. Tailscale が Synology に導入済みで、tailnet へ参加できている
3. 保存用フォルダを作れる
4. 管理者が 1 回だけ Tailscale CLI を実行できる

作るフォルダ例:

1. `docker/kouku-kinou`
2. `docker/kouku-kinou/data`

いちばん確実なのは、配布物の `package/kouku-kinou-admin-deploy` の中身をそのまま `docker/kouku-kinou` へコピーする方法です。

最低限でも、`docker/kouku-kinou` 直下に次を置きます。

1. `compose.yaml`
2. `.env`
3. `Dockerfile`
4. `server.py`
5. `index.html`
6. `assets` フォルダ
7. `README.html` などの HTML / PDF 資料一式
8. `data` フォルダ

`data` フォルダの中には、少なくとも次を置きます。

1. `records.db`
2. 必要に応じて `records.backup-*.db`

## .env の確認

実運用前に次を確認してください。

1. `KOUKU_KINOU_AUTH_MODE=tailscale-or-password`
2. `KOUKU_KINOU_PASSWORD`: 管理者用の強いパスワードへ変更
3. `KOUKU_KINOU_SECURE_COOKIE=1`: このままでよい
4. `KOUKU_KINOU_DATA_DIR=./data`: Synology で迷う場合は `/volume1/docker/kouku-kinou/data` のような絶対パスへ変更
5. `KOUKU_KINOU_ALLOWED_NETWORKS=`: 通常は空欄のままでよい
6. `KOUKU_KINOU_TRUST_PROXY=0`: 通常はこのままでよい

`tailscale-or-password` の意味:

1. 利用者が Tailscale の HTTPS URL から入れば自動認証される
2. うまくヘッダーが届かない時だけ、管理者用パスワードでも入れる

`KOUKU_KINOU_DATA_DIR` の考え方:

1. 既定値の `./data` は `compose.yaml` と同じフォルダの `data` を使います
2. Synology で場所を明示したい場合は `/volume1/docker/kouku-kinou/data` のような共有フォルダ配下を指定します
3. `unable to open database file` が出たときは、まずこの値と実フォルダの存在を見直します

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

もし `https://diskstation.tail632bc4.ts.net/api/health` が `{"status": "error", "error": "unable to open database file"}` を返した場合は次です。

1. `data` フォルダを Synology 上で作成済みか確認する
2. `.env` の `KOUKU_KINOU_DATA_DIR` を絶対パスへ変更する
3. Container Manager でプロジェクトを再ビルドする
4. `data/records.db`、`data/records.db-wal`、`data/records.db-shm` が作成されるか確認する
5. それでも直らない場合はコンテナログで `/data` まわりの権限エラーを確認する

## 利用者への配布

利用者には次の 2 つを渡します。

1. Tailscale の接続方法
2. アプリ URL または `TailscaleClientLauncher.cmd` 一式

Windows 利用者向けの簡易起動ツールは次の 3 ファイルです。

1. `TailscaleClientLauncher.cmd`
2. `TailscaleClientLauncher.ps1`
3. `TailscaleClientLauncher.settings.json`

`TailscaleClientLauncher.settings.json` の `appUrl` は `https://diskstation.tail632bc4.ts.net/` に設定済みです。URL を変更した時だけ、このファイルも合わせて更新してください。

配布前に `organizationName`、`appUrl`、`supportText`、`supportContact` を現場向けに更新してください。特に `supportContact` は、利用者が困ったときの連絡先になるため、空欄のまま配らないほうが安全です。

操作手順も一緒に渡すなら、`TAILSCALE_CLIENT_GUIDE_JA.pdf` を同梱するとそのまま案内に使えます。

タブレット利用者にはファイル一式を配るより、次の案内だけを渡すほうが簡単です。

1. App Store / Google Play で Tailscale を入れること
2. 管理者が指定した方法で Tailscale にサインインすること
3. `https://diskstation.tail632bc4.ts.net/` をブラウザーで開くこと

利用者向けの説明文は [TAILSCALE_TABLET_GUIDE_JA.html](TAILSCALE_TABLET_GUIDE_JA.html) をそのまま使えます。

短い配布メッセージは [TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html](TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.html)、紙で渡す案内は [TAILSCALE_TABLET_QR_SHEET_JA.html](TAILSCALE_TABLET_QR_SHEET_JA.html) を使えます。

配布用の見やすい版としては `TAILSCALE_TABLET_GUIDE_JA.pdf`、`TAILSCALE_TABLET_MESSAGE_TEMPLATE_JA.pdf`、`TAILSCALE_TABLET_QR_SHEET_JA.pdf` も使えます。

## バックアップ

最重要なのは `data/records.db` です。記録本体と共有設定がここに入ります。

おすすめ:

1. 1 日 1 回バックアップ
2. 別フォルダへ世代管理
3. 週 1 回は復元テスト

担当者一覧とかかりつけ医一覧も `shared_settings` テーブルとしてこの DB に入るため、`records.db` のバックアップ 1 つで両方を保護できます。

## 更新手順

アプリを更新する流れは次のとおりです。

1. 先に `data/records.db` をバックアップ
2. 新しいファイルで `server.py`、`Dockerfile`、`README.html` などを上書き
3. Container Manager でプロジェクトを再ビルドして起動します。DSM の画面で再ビルド操作が見当たらない場合は、同じフォルダを指定してプロジェクトを作り直します。
4. 必要なら `tailscale serve status` を確認
5. `https://diskstation.tail632bc4.ts.net/` でログイン、保存、一覧表示、検索を確認
6. 同一利用者・同一評価日の更新挙動を 1 件だけ確認

### 今回のように `server.py` を更新した時の最短手順

今回の共有設定対応は `server.py` の再配備だけで反映できます。`data/records.db` はそのまま残してよく、初回起動時に不足している `shared_settings` テーブルを自動作成します。手作業の DB 変換は不要です。

#### A. Container Manager の画面で反映する

1. DSM にログインします。
2. File Station で `docker/kouku-kinou/data/records.db` を `records.backup-YYYYMMDD-HHMM.db` のような名前でコピーします。
3. File Station で `docker/kouku-kinou/server.py` を新しいものへ上書きします。
4. 今回 `Dockerfile` や `README.html` も変えた場合だけ、それらも同じフォルダへ上書きします。
5. Container Manager を開きます。
6. 「プロジェクト」で `kouku-kinou` を選びます。
7. いったん停止します。
8. 画面に「再作成」「ビルド」「更新」などの項目があれば、それを使って同じ `docker/kouku-kinou/compose.yaml` から再作成します。
9. その操作が見当たらない場合は、「作成」から同じフォルダ `docker/kouku-kinou` を指定し直し、同じ `compose.yaml` を読み込んで起動します。
10. コンテナ名が `kouku-kinou`、状態が「実行中」になっていることを確認します。
11. ログにエラーが出ていないことを確認します。

#### B. SSH で反映できる場合の最短コマンド

SSH で Synology に入り、`docker compose` が使える環境なら次で反映できます。

```powershell
ssh 管理者ユーザー名@NASのIP
sudo -i
cd /volume1/docker/kouku-kinou
cp data/records.db data/records.backup-$(date +%Y%m%d-%H%M).db
docker compose up --build -d
docker compose ps
```

`docker compose` が使えない NAS では、上の A の Container Manager 手順を使ってください。

#### 反映後に必ず確認すること

1. `https://diskstation.tail632bc4.ts.net/api/health` が開ける
2. トップ画面が開く
3. ヘッダー右上の歯車から設定画面を開ける
4. 担当者一覧またはかかりつけ医一覧へ 1 件追加し、保存できる
5. ページ再読込後もその候補が残る
6. 利用者情報タブのプルダウンへ同じ候補が出る
7. 確認用に追加した候補を削除し、再読込後に消える

#### 今回の変更で覚えておくこと

1. 共有設定は `data/records.db` に入るので、NAS をまたいで別 DB を使わない限り端末ごとの差は出ません。
2. 単なるコンテナ再起動だけでは古いイメージのままなので、`server.py` を差し替えた時は再ビルドまたは再作成が必要です。
3. `tailscale serve` の設定はそのまま使えるので、通常はやり直し不要です。

補足:

1. この構成ではアプリ本体は Docker イメージに含まれます。コードやヘルプ文書を変えた時は、単なる再起動では古いイメージのままです。
2. 永続化しているのは `./data:/data` だけなので、`data` フォルダを消さなければ `records.db` は残ります。

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