# GitHub ブラウザで index.html を安全に差し替える手順

この資料は、非エンジニアの担当者が GitHub のブラウザ画面から本番用の `index.html` を更新するときの手順です。

この手順で触るのは `index.html` だけです。`server.py`、`compose.yaml`、`Dockerfile` などは触りません。

## 最初に覚えること

1. 受け取った HTML は、いきなりリポジトリ直下の `index.html` に上書きしません。
2. まず別名ファイルとして保存し、PowerShell の検証コマンドを通します。
3. `Client HTML validation: OK (managed)` または `Client HTML validation: OK (legacy-source)` が出たときだけ受け入れます。
4. 本番反映は `main` に入った commit だけが対象です。

## 事前に確認すること

1. Claude などから受け取った完成版の `index.html` が手元にある
2. そのファイルは一部分ではなく、最初から最後まで全文が入っている
3. 変更は `main` ブランチへ直接 commit するか、最終的に `main` へ merge する
4. `server.py` や `compose.yaml` は今回の作業対象ではない

受け入れてはいけないもの:

1. `index.html` の一部分だけ
2. 途中が省略された HTML
3. `server.py` も直す前提の提案
4. 検証コマンドで失敗した HTML

## 手順 1. 受け取った HTML を別名で保存する

1. 受け取った HTML を、まず別名のファイルとして保存します。
2. たとえば `index_2026-05-20.html` のような名前にします。
3. この時点では、リポジトリ直下の `index.html` はまだ上書きしません。

## 手順 2. PowerShell で検証する

次のコマンドで受け入れ可否を確認します。

```powershell
& "C:\Users\user\AppData\Local\Microsoft\WindowsApps\python.exe" .\server.py --validate-client-html "C:\path\to\index_new.html"
```

判定ルール:

1. `Client HTML validation: OK (managed)` が出たら受け入れてよい
2. `Client HTML validation: OK (legacy-source)` が出たら受け入れてよい
3. `Client HTML validation failed: ...` が出たら受け入れない

失敗した場合は、その HTML で GitHub 更新を進めません。作成者へ差し戻してください。

## 手順 3. GitHub のブラウザ画面で index.html を置き換える

1. GitHub でこのリポジトリを開きます。
2. リポジトリ直下の `index.html` を開きます。
3. 新しいファイルをアップロードできる場合は、`Add file` から `Upload files` を開き、同名の `index.html` を置き換えます。
4. アップロードで置き換えにくい場合は、既存の `index.html` を開いて編集ボタンから中身を丸ごと貼り替えます。
5. 差し替えるときは、一部分ではなく全文を丸ごと入れ替えます。
6. 変更内容を確認し、分かりやすい commit メッセージを入れます。
7. `Commit directly to the main branch` を選ぶか、Pull Request を `main` へ merge します。

重要:

1. 本番反映は `main` に入った commit だけが対象です。
2. `index.html` 以外の場所へアップロードしないでください。

## commit 後に起こること

1. GitHub Actions の `Deploy to Synology` が自動で起動します。
2. Synology 側で最新 commit を取り込みます。
3. `index.html` を含む変更は自動で rebuild 対象になり、`docker compose up --build -d` が実行されます。
4. 通常は 1 分から 3 分ほどで反映が終わります。

## 手順 4. Actions と本番画面を確認する

1. GitHub の `Actions` タブで `Deploy to Synology` が成功になっていることを確認します。
2. 本番 URL `https://diskstation.tail632bc4.ts.net/` を開きます。
3. 必要ならログインします。
4. 実際のアプリ画面で、変更した箇所を確認します。
5. あわせて、保存と記録一覧の表示も確認します。
6. 古い画面が見える場合は、ブラウザーを再読み込みします。

## うまく反映されないとき

1. 変更が `main` に入っているか確認します。
2. `Actions` タブで失敗していないか確認します。
3. `index.html` 以外の場所へアップロードしていないか確認します。
4. `index.html` を一部分だけ差し替えていないか確認します。
5. 事前の検証コマンドが成功していたか確認します。

## 元に戻したいとき

1. 直前の正常な `index.html` をもう一度アップロードして commit します。
2. または GitHub の commit 履歴から対象 commit を取り消して `main` に戻します。
3. 戻したあとも、`Deploy to Synology` と本番画面を確認します。

ここだけ覚えれば大丈夫: 受け取った HTML は別名で保存し、検証に通ったときだけ GitHub の `index.html` と差し替えます。反映後は `Deploy to Synology` と本番画面の両方を確認します。