# 初心者向け運用マニュアル

この資料は、PC にあまり慣れていない人向けの「使い方」と「運用のしかた」の説明書です。今の構成では、アプリを開く入口を Tailscale に統一しています。

## このアプリでできること

このアプリは、口腔機能と栄養評価の記録を残すためのものです。

主な用途:

1. 利用者情報の入力
2. 口腔機能の評価
3. MNA-SF の入力
4. コメントの記録
5. 保存した記録の一覧表示
6. 印刷や PDF 出力

## このアプリの入口

利用者が見る入口は次の 2 つです。

1. Tailscale の接続
2. アプリの HTTPS URL

つまり、先に Tailscale へつながってからアプリを開きます。社外や別拠点からでも、同じやり方で使えます。

現在の正式 URL は `https://diskstation.tail632bc4.ts.net/` です。Windows PC では通常 `TailscaleClientLauncher.cmd` の「アプリを開く」から、タブレットでは Tailscale アプリ接続後にブラウザーから同じ URL を開きます。

## アプリの全体構成

難しい言葉を使わずに言うと、次の 4 つでできています。

1. 画面: ブラウザーで見る部分
2. サーバー: 画面とデータをまとめる裏側
3. データ: 保存された記録そのもの
4. Tailscale: 安全な接続の通り道

## フォルダとファイルの役割

大事なものだけ覚えれば十分です。

1. `index.html`: 元の画面デザインのもとになるファイル
2. `server.py`: アプリを動かす本体
3. `compose.yaml`: Docker で起動する設定
4. `.env`: 認証モードや管理者パスワードの設定
5. `data/records.db`: 保存された記録データ
6. `TailscaleClientLauncher.cmd`: 利用者向けの簡易起動
7. `TailscaleClientLauncher.settings.json`: 簡易起動ツールの URL 設定

一番大事なのは `data/records.db` です。

## 初めて使う人の流れ

初回は次の順で進めます。

1. `TailscaleClientLauncher.cmd` を開く
2. 「Tailscale をダウンロード」を押してインストールする
3. 「Tailscale を起動」を押してサインインする
4. 状態が接続済みになったら「アプリを開く」を押す

ブラウザーを直接使う場合は `https://diskstation.tail632bc4.ts.net/` を開きます。

Windows PC の詳しい画面操作は [TAILSCALE_CLIENT_GUIDE_JA.md](TAILSCALE_CLIENT_GUIDE_JA.md) を見てください。タブレットの案内は [TAILSCALE_TABLET_GUIDE_JA.md](TAILSCALE_TABLET_GUIDE_JA.md) を見てください。

## ふだん使う人の流れ

毎日の使い方は次のとおりです。

1. `TailscaleClientLauncher.cmd` を開く
2. 「状態を確認」で Tailscale が接続済みか見る
3. 「アプリを開く」を押す
4. 利用者情報や評価を入力する
5. 保存ボタンを押す
6. 必要なら記録一覧で氏名や生年月日を検索して読み込む

## 保存のしくみ

保存ボタンを押すと、入力した内容は NAS 側のデータベースに入ります。だから、別の PC やタブレットから開いても同じ記録が見えます。

重複の扱い:

1. 利用者は `氏名 + 生年月日` で見分けます
2. 同じ利用者の同じ評価日は、二重登録ではなく前の記録を更新します
3. 同じ利用者でも評価日が違えば、履歴として別に残ります

## ログインについて

今の構成では、Tailscale 経由で入ると自動認証になる場合があります。管理者が `tailscale-or-password` にしている場合は、必要なときだけパスワード画面も出ます。

覚えること:

1. まず Tailscale をつないでから開く
2. パスワード画面が出たら管理者に確認する
3. 共用 PC では作業後にブラウザーを閉じる

## 起動と停止

通常利用者は、サーバーの起動や停止を触らなくて大丈夫です。管理する人だけが操作します。

管理者が覚えること:

1. アプリが見られないときはコンテナが止まっていないか確認
2. `tailscale serve status` で HTTPS 転送が残っているか確認
3. `http://127.0.0.1:8010/api/health` または `docker compose ps` で healthy か確認
4. 電源を切る前に保存中の作業がないか確認

## バックアップ

記録を守るために、バックアップは必須です。

対象:

1. `data/records.db`

おすすめ:

1. 毎日 1 回バックアップ
2. 1 週間分以上を残す
3. 月 1 回は復元確認をする

## やってはいけないこと

次のことはしないでください。

1. `data/records.db` を手で開いて編集する
2. `.env` をよく分からないまま書き換える
3. `TailscaleClientLauncher.settings.json` の URL を勝手に変える
4. 動いている最中にフォルダを削除する
5. 他のアプリのファイルと混ぜる

## 困ったときの見分け方

### 1. 「Tailscale 接続が必要です」と出る

考えられる原因:

1. Tailscale が未接続
2. helper を使わず、別の URL を開いている
3. Synology 側の Tailscale Serve が止まっている

### 2. パスワード画面は出るが入れない

考えられる原因:

1. パスワード違い
2. `.env` の設定変更後に再起動していない

### 3. 画面が開かない

考えられる原因:

1. NAS が止まっている
2. コンテナが止まっている
3. Tailscale が未接続
4. URL が違う

### 4. 保存できない

考えられる原因:

1. `data` フォルダに書き込みできない
2. コンテナ内部でエラーが出ている
3. 生年月日が未入力で、保存条件を満たしていない

### 5. 別端末で記録が見えない

考えられる原因:

1. 片方が別 URL を見ている
2. 保存に失敗している
3. 別の NAS や別環境を見ている

## 管理者の定期点検

週 1 回でよいので、次を見てください。

1. Tailscale 接続済みの PC から画面を開けるか
2. 保存できるか
3. 記録一覧が出るか
4. 記録一覧の検索が使えるか
5. `data/records.db` が更新されているか
6. バックアップが取れているか

## パスワード変更方法

1. `.env` を開く
2. `KOUKU_KINOU_PASSWORD=` の右側を書き換える
3. アプリを再起動する
4. 新しいパスワードでログイン確認する

## アプリの更新方法

1. 先に `data/records.db` をコピーしてバックアップ
2. 新しいファイルで上書き
3. 再起動
4. Tailscale URL からログイン、保存、一覧、検索の確認

## このアプリの運用で一番大切なこと

1. Tailscale 接続方法を利用者へ統一して案内する
2. `data/records.db` を必ずバックアップする
3. 設定変更後は動作確認する
4. いきなり本番で変更しない

## 迷ったら見る順番

1. まず [README.md](README.md)
2. Synology への設置は [DEPLOY_SYNOLOGY_JA.md](DEPLOY_SYNOLOGY_JA.md)
3. Windows 利用者の初回案内は [TAILSCALE_CLIENT_GUIDE_JA.md](TAILSCALE_CLIENT_GUIDE_JA.md)
4. タブレット利用者の初回案内は [TAILSCALE_TABLET_GUIDE_JA.md](TAILSCALE_TABLET_GUIDE_JA.md)
4. ふだんの運用はこの [OPERATIONS_MANUAL_JA.md](OPERATIONS_MANUAL_JA.md)