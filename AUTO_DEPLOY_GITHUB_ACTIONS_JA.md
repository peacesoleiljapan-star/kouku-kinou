# GitHub Actions + Tailscale + Synology SSH で自動反映する手順

この構成は、GitHub の main ブランチに push された変更を GitHub Actions で検知し、Tailscale 経由で Synology NAS の通常の SSH サーバーへ接続して本番環境へ反映します。

重要: Synology 版 Tailscale では Tailscale SSH サーバーは動きません。公式ドキュメントでも、Synology では DSM が提供する SSH サーバーを使う制約になっています。

今回の実装では、GitHub 上で main に入った最新コミットを Synology 側で checkout し、対象ファイルの差分に応じて docker compose up --build -d を実行します。Synology では bind mount による差し替えへ依存せず、rebuild ベースで本番を更新します。

初回デプロイ時に `TS_REPO_DIR` がまだ存在しなくても、workflow から渡す `DEPLOY_REPO_URL` を使って NAS 側で自動 clone できます。

## 仕組み

1. GitHub Actions が main ブランチの更新を検知します。
2. Actions の一時 runner が Tailscale に参加します。
3. runner が Tailscale ネットワークへ参加します。
4. runner が Synology の通常の SSH サーバーへ入り、scripts/deploy_synology.sh を実行します。
5. NAS 側の `TS_REPO_DIR` が無ければ clone し、あれば git fetch と checkout を行います。
6. Synology 側の tracked file に差分が残っていれば、対象 commit に戻してから続行します。
7. NAS 側で最新コミットとの差分を見て、rebuild が必要か判定します。
8. index.html、assets、配布資料、起動ツール、server.py、Dockerfile、compose.yaml などが変わっていれば docker compose up --build -d を実行します。
9. コンテナの health check が通ったら反映完了です。

## この構成が向いている理由

1. NAS をインターネットへ直接公開しません。
2. GitHub 側からの接続は Tailscale 内だけで閉じます。
3. Synology の bind mount 挙動に依存しないため、本番反映の挙動が安定します。
4. Actions 側は毎回 ephemeral node なので、長く残る踏み台サーバーが要りません。

## 事前に入れた実装

1. compose.yaml では永続データ用の data だけをホストへ保持し、アプリ本体は Docker イメージに含めます。
2. server.py にはテンプレート再読込の仕組みがありますが、本番反映は rebuild ベースを正とします。
3. .github/workflows/deploy-synology.yml が自動デプロイを実行します。
4. scripts/deploy_synology.sh が Synology 上の更新処理を担当します。

## 1 回だけ行う Synology 側セットアップ

手作業を減らしたい場合は、Windows 側で [setup_synology_actions_ssh.cmd](setup_synology_actions_ssh.cmd) を実行してください。次をまとめて再実行できます。

1. GitHub Actions 用 SSH 鍵の再利用または生成
2. Synology への公開鍵再登録
3. Synology ホーム権限と .ssh 権限の修復
4. 鍵ログイン確認
6. 必要なら root 用にも同じ鍵を追加登録

Synology 故障や初期化後の復旧時は、このスクリプトを再実行するのが最短です。

GitHub Variables と SSH secrets までまとめて再投入したい場合は、Windows 側で [setup_github_actions_deploy.cmd](setup_github_actions_deploy.cmd) を使ってください。

### 1. 作業ディレクトリを git clone で配置する

本番フォルダは zip 展開ではなく git clone にしてください。Actions からは NAS 上で git pull 相当を実行します。

例:

```sh
sudo -i
mkdir -p /volume1/docker
cd /volume1/docker
git clone <このリポジトリの読み取り用 URL> kouku-kinou
cd /volume1/docker/kouku-kinou
cp .env.example .env
mkdir -p data
docker compose up --build -d
```

補足:

1. GitHub 認証は read-only deploy key か fine-grained PAT を推奨します。
2. .env と data は git 管理外のまま残ります。
3. すでに `TS_REPO_DIR` を空フォルダで用意している場合は、そこを git 作業ツリーにするか、いったん消して workflow の自動 clone に任せます。

### 2. Synology の SSH サーバーを使う

Tailscale SSH は Synology で使えないため、DSM の SSH サーバーをそのまま使います。

確認すること:

1. DSM の Control Panel > Terminal & SNMP で SSH が有効
2. SSH ポート番号を把握している
3. GitHub Actions からログインさせるユーザーを決める
4. そのユーザーで公開鍵認証が使える

現在の環境では次で再実行できます。

```powershell
setup_synology_actions_ssh.cmd
setup_synology_actions_ssh.cmd -RegisterRootKey
```

既定値:

1. host: `diskstation.tail632bc4.ts.net`
2. port: `123`
3. user: `Ao1mini5trAtor`

別の値で実行する場合の例:

```powershell
setup_synology_actions_ssh.cmd -SynologyHost diskstation.tail632bc4.ts.net -Port 123 -User Ao1mini5trAtor
```

### 3. GitHub Actions 用の SSH 公開鍵を Synology に登録する

GitHub Actions は対話的にパスワードを入れられないため、SSH 鍵認証を使います。

1. GitHub Actions 用の秘密鍵を 1 組作る
2. 公開鍵を Synology 側の対象ユーザーの ~/.ssh/authorized_keys に追加する
3. 秘密鍵は GitHub Secret TS_NAS_SSH_PRIVATE_KEY に入れる
4. 可能なら known_hosts も GitHub Secret TS_NAS_KNOWN_HOSTS に入れる

### 4. Tailscale ポリシーで CI 用タグから Synology の SSH ポートを許可する

GitHub Actions 側は tag:ci で参加させる前提です。Tailscale 管理画面のポリシーで、tag:ci から Synology の SSH ポートへの通信を許可してください。

最低限の考え方:

1. source は tag:ci
2. destination は Synology のマシン
3. port は Synology の SSH ポート。例 22 または 123

既存ポリシー形式が ACL か grants かで記法が変わるため、ここは現在の tailnet ポリシーに合わせて追記してください。

## GitHub 側の設定

### Repository Variables

1. TS_NAS_HOST: Synology の MagicDNS 名または Tailscale IP
2. TS_NAS_SSH_USER: Synology の SSH ログインユーザー名
3. TS_NAS_SSH_PORT: Synology の SSH ポート。未設定なら 22
4. TS_REPO_DIR: NAS 上のリポジトリ配置先。例 /volume1/docker/kouku-kinou

現在の環境では、host は `diskstation.tail632bc4.ts.net`、port は `123`、repo dir は `/volume1/docker/kouku-kinou` を使う想定です。

### Secrets

推奨は OIDC です。

1. TS_OAUTH_CLIENT_ID
2. TS_AUDIENCE
3. TS_NAS_SSH_PRIVATE_KEY
4. TS_NAS_KNOWN_HOSTS: 可能なら設定。未設定時は workflow が ssh-keyscan を実行

`setup_synology_actions_ssh.ps1 -PrintGitHubValues` を実行すると、SSH 秘密鍵と known_hosts をその場で表示できます。

`setup_github_actions_deploy.cmd` は次をまとめて行えます。

1. TS_NAS_HOST などの Repository Variables 更新
2. TS_NAS_SSH_PRIVATE_KEY と TS_NAS_KNOWN_HOSTS の Secrets 更新
3. 必要なら TAILSCALE_AUTHKEY の安全な対話入力
4. 必要なら deploy-synology.yml の手動実行

例:

```powershell
setup_github_actions_deploy.cmd
setup_github_actions_deploy.cmd -User root
setup_github_actions_deploy.cmd -PromptForTailscaleAuthKey -DispatchWorkflow
```

Docker を sudo なしで実行できない Synology では、`setup_synology_actions_ssh.cmd -RegisterRootKey` を先に実行し、その後 `setup_github_actions_deploy.cmd -User root` で GitHub Variables を更新する構成が簡単です。

すぐ動かすためのフォールバックとして auth key も使えます。

1. TAILSCALE_AUTHKEY
2. TS_NAS_SSH_PRIVATE_KEY
3. TS_NAS_KNOWN_HOSTS

auth key を使うなら、tag 付き、ephemeral、reusable、可能なら pre-approved の key にしてください。

## Tailscale 側の推奨設定

### 第一候補: Workload Identity Federation

1. Tailscale 側で GitHub Actions 用の federated identity を作る
2. auth_keys scope を付ける
3. tag:ci を付けられるようにする
4. client id を TS_OAUTH_CLIENT_ID、audience を TS_AUDIENCE として GitHub Secrets に入れる

この方法だと、GitHub に長期の Tailscale 認証キーを置かずに済みます。

### 代替: Auth Key

OIDC をまだ使わない場合は TAILSCALE_AUTHKEY だけでも動きます。

## 実際のデプロイ動作

### index.html や配布ファイルを更新した場合

1. GitHub のブラウザ画面で index.html を編集して commit
2. Actions が起動
3. Synology で git 更新
4. index.html は rebuild 対象なので、docker compose up --build -d が実行される
5. health check が通ると、ログイン後のアプリ画面へ反映される

### server.py や Dockerfile を更新した場合

1. GitHub へ push
2. Actions が Synology に入り、docker compose up --build -d を実行
3. /api/health が通れば完了

### rebuild 対象の主なファイル

1. index.html
2. assets 配下のファイル
3. README.md などの配布資料
4. TailscaleClientLauncher 一式
5. server.py
6. Dockerfile
7. compose.yaml
8. .env.example

## 手動実行

GitHub Actions の workflow_dispatch から手動実行できます。force_rebuild を true にすると、差分判定に関係なく再ビルドします。

## 障害時の見方

### Actions が Tailscale 接続で失敗する

1. TS_NAS_HOST が正しいか確認
2. tag:ci が Tailscale 側で許可されているか確認
3. OIDC を使う場合は TS_OAUTH_CLIENT_ID と TS_AUDIENCE を確認

### SSH で失敗する

1. DSM の SSH が有効か確認
2. Tailscale ポリシーで tag:ci から TS_NAS_HOST の SSH ポートが許可されているか確認
3. TS_NAS_SSH_PRIVATE_KEY が正しいか確認
4. TS_NAS_SSH_PORT が実際のポートと一致しているか確認

### docker 実行権限で失敗する

1. Synology 側の SSH ユーザーが docker を直接実行できない場合があります。
2. deploy script は root または passwordless sudo を前提にしています。
3. 通常ユーザーで失敗する場合は `setup_synology_actions_ssh.cmd -RegisterRootKey` を実行します。
4. その後 `setup_github_actions_deploy.cmd -User root` を実行して、GitHub Variables の `TS_NAS_SSH_USER` を root に切り替えます。

### デプロイ時に Tracked local changes exist と出る

NAS 側の作業ツリーで、git 管理対象ファイルを手で直しています。自動化を壊す原因になるため、NAS 側の tracked file 直接編集はやめて GitHub を正本にしてください。

現在の deploy script は、tracked file の差分を見つけた場合はその差分を表示したうえで、Synology 側の tracked file を GitHub 側の対象 commit へ自動で戻してから続行します。`.env` や `data` などの Git 管理対象外ファイルはそのまま残ります。

### 反映されない

1. 変更が main に commit または merge されているか確認
2. GitHub Actions の Deploy to Synology が成功しているか確認
3. docker compose ps で kouku-kinou が healthy か確認
4. /api/health だけでなく、ログイン後のアプリ画面で確認する
5. index.html や配布資料を変えたのに rebuild されない場合は、scripts/deploy_synology.sh の rebuild 対象に含まれているか確認する

## 運用ルール

1. 非エンジニアの更新対象は index.html に限定し、Claude が出した完成版を丸ごと置き換える
2. 本番側で直接ファイルを直さない
3. GitHub のブラウザ更新は main へ commit するか、main へ merge する
4. server.py や compose.yaml の変更はエンジニアが管理する
5. data フォルダと .env は NAS ローカルで保全する
6. Synology では Tailscale SSH ではなく DSM の SSH サーバーを使う