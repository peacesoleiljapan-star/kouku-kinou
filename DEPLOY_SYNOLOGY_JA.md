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

GitHub の `index.html` 更新をそのまま本番へ自動反映したい場合は、[AUTO_DEPLOY_GITHUB_ACTIONS_JA.md](AUTO_DEPLOY_GITHUB_ACTIONS_JA.md) を併用してください。

## この構成でやらないこと

1. Synology 独自ドメインの取得
2. DSM リバースプロキシ設定
3. ルーターでのポート開放
4. Tailscale Funnel によるインターネット公開

Tailscale Serve は tailnet 内限定です。公開 URL を全世界へ出したい用途には向きません。

## このアプリの置き場所

現在のおすすめ配置は、Synology 上にこのリポジトリ一式を置き、その中で `docker compose` を実行する形です。

主な置き場所:

1. `/volume1/docker/kouku-kinou`: リポジトリまたは配置フォルダ
2. `/volume1/docker/kouku-kinou/compose.yaml`: アプリ全体を起動する設定
3. `/volume1/docker/kouku-kinou/.env`: 認証モードや管理者パスワード
4. `/volume1/docker/kouku-kinou/server.py`: アプリ本体を配信するサーバー
5. `/volume1/docker/kouku-kinou/index.html`: 元の画面ソース
6. `/volume1/docker/kouku-kinou/data/records.db`: 記録データと共有設定。最重要ファイル

GitHub Actions で自動反映する場合は、このフォルダを git の作業ツリーにしておく構成が最も扱いやすくなります。

## 事前準備

Synology 側で次を確認します。

1. Container Manager が入っている
2. Tailscale が Synology に導入済みで、tailnet へ参加できている
3. 保存用フォルダを作れる
4. 管理者が 1 回だけ Tailscale CLI を実行できる
5. GitHub Actions を使う場合は、Synology の SSH に入れること

作るフォルダ例:

1. `docker/kouku-kinou`
2. `docker/kouku-kinou/data`

手動配置だけで始める場合は、このフォルダに以下を置きます。

1. `compose.yaml`
2. `.env`
3. `server.py`
4. `index.html`

GitHub Actions 自動反映も使う場合は、zip 展開より git clone をおすすめします。現在の deploy script は NAS 上の git 作業ツリーを更新し、差分に応じて rebuild する構成です。

Windows から SSH 鍵や GitHub Variables / Secrets をまとめて再設定したい場合は、次を使えます。

1. `setup_synology_actions_ssh.cmd`
2. `setup_github_actions_deploy.cmd`

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

GitHub Actions 自動反映も使う場合は、この段階で一度 `https://diskstation.tail632bc4.ts.net/` が開けることまで確認しておくと、その後の切り分けが楽になります。

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

最重要なのは `data/records.db` です。記録本体と共有設定がここに入ります。

おすすめ:

1. 1 日 1 回バックアップ
2. 別フォルダへ世代管理
3. 週 1 回は復元テスト

担当者一覧とかかりつけ医一覧も `shared_settings` テーブルとしてこの DB に入るため、`records.db` のバックアップ 1 つで両方を保護できます。

## 更新手順

日常更新では、GitHub を正本にして反映する運用をおすすめします。NAS 側の tracked file を直接編集すると、自動反映と競合しやすくなります。

### 標準手順: GitHub Actions で反映する

1. GitHub で `main` に変更を入れます。
2. `Deploy to Synology` が成功することを確認します。
3. 本番 URL でログイン、保存、記録一覧の表示を確認します。
4. 必要なら `tailscale serve status` も確認します。

現在の deploy script は、`index.html`、`assets`、配布資料、起動ツール、`server.py`、`Dockerfile`、`compose.yaml` などの変更を検知すると `docker compose up --build -d` を実行します。

補足:

1. NAS 側に tracked file の変更が残っていた場合は、deploy script が対象 commit に合わせて戻してから続行します。
2. `.env` と `data` は Git 管理対象外なので、そのまま残ります。

### 手動で Synology へ反映する場合

GitHub Actions を使わずに NAS 側で直接更新する場合は、次の順で進めます。

1. 先に `data/records.db` をバックアップします。
2. 更新したいファイルを Synology 上の配置フォルダへ上書きします。
3. `docker compose up --build -d` で再ビルドして起動します。
4. `docker compose ps` で `healthy` を確認します。
5. `https://diskstation.tail632bc4.ts.net/` でログイン、保存、一覧表示、検索を確認します。

SSH で反映できる場合の例:

```powershell
ssh 管理者ユーザー名@NASのIP
sudo -i
cd /volume1/docker/kouku-kinou
cp data/records.db data/records.backup-$(date +%Y%m%d-%H%M).db
docker compose up --build -d
docker compose ps
```

`docker compose` が通常ユーザーで動かない NAS では、root または passwordless sudo が必要です。GitHub Actions で root を使う場合は、次の順で設定し直すと簡単です。

1. `setup_synology_actions_ssh.cmd -RegisterRootKey`
2. `setup_github_actions_deploy.cmd -User root`

### 反映後に必ず確認すること

1. `https://diskstation.tail632bc4.ts.net/api/health` が開ける
2. トップ画面が開く
3. ログインできる
4. 保存できる
5. 記録一覧が表示できる
6. 氏名、ふりがな、生年月日、評価日で検索できる
7. 同一利用者・同一評価日の再保存が上書き更新になる

ここだけ覚えれば大丈夫: 初期配置後の日常更新は GitHub を正本にします。手動で Synology を更新したときは、単なる再起動ではなく `docker compose up --build -d` で再ビルドし、本番 URL で動作確認まで行います。

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