# GitHub ブラウザで index.html を差し替える手順

この手順だけで本番画面を更新できます。担当者が触るのは `index.html` だけです。

## 事前に確認すること

1. Claude から受け取った完成版の `index.html` が手元にある
2. 変更は `main` ブランチへ直接 commit するか、最終的に `main` へ merge する
3. `server.py` や `compose.yaml` は触らない

重要:

- 部分的なコード断片ではなく、Claude が出力した `index.html` 全体を丸ごと置き換えてください。
- 本番反映は `main` に入ったコミットだけが対象です。

## 手順

1. GitHub でこのリポジトリを開く
2. リポジトリ直下の `index.html` を更新する
3. 新しいファイルをアップロードできる場合は、`Add file` から `Upload files` を開き、同名の `index.html` を置き換える
4. アップロードで置き換えにくい場合は、既存の `index.html` を開いて編集ボタンから中身を丸ごと貼り替える
5. 変更内容を確認し、分かりやすいコミットメッセージを入れる
6. `Commit directly to the main branch` を選ぶか、Pull Request を `main` へ merge する

## commit 後に起こること

1. GitHub Actions の `Deploy to Synology` が自動で起動する
2. Synology 側で最新コミットを取り込み、`index.html` を含む変更なら自動で rebuild される
3. 通常は 1 分から 3 分ほどで反映が終わる

## 確認方法

1. GitHub の `Actions` タブで `Deploy to Synology` が成功になっていることを確認する
2. 本番 URL を開く
3. 必要ならログインして、実際のアプリ画面で変更を確認する
4. 古い画面が見える場合は、ブラウザを再読み込みする

## うまく反映されないとき

1. 変更が `main` に入っているか確認する
2. `Actions` タブで失敗していないか確認する
3. `index.html` 以外の場所へアップロードしていないか確認する
4. `index.html` を一部分だけ差し替えていないか確認する

## 元に戻したいとき

1. 直前の正常な `index.html` をもう一度アップロードして commit する
2. または GitHub の commit 履歴から対象コミットを取り消して `main` に戻す