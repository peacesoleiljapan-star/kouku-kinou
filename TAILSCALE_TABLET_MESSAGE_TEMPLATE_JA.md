# タブレット利用者向け案内文テンプレート

この資料は、管理者が iPad / Android タブレット利用者へそのまま送れる案内文のひな形です。

## 先に確認すること

送る前に、次の 2 点だけ確認します。

1. 利用者が Tailscale にサインインするときの案内方法
2. アプリ URL が `https://diskstation.tail632bc4.ts.net/` のままでよいこと

## 短文テンプレート

LINE やチャットで短く送る場合の例です。

```text
タブレットで使う方へ

1. Tailscale をインストールしてください
2. 管理者が案内した方法でサインインしてください
3. 接続後に次の URL を開いてください
https://diskstation.tail632bc4.ts.net/
```

もう少し説明を足したい場合は、次の版を使います。

```text
タブレットで使う方へ

1. App Store または Google Play で Tailscale をインストールしてください
2. Tailscale を開いて、管理者から案内した方法でサインインしてください
3. 接続後に次の URL を開いてください
https://diskstation.tail632bc4.ts.net/

詳しい手順は配布した「タブレット利用者向け Tailscale 接続ガイド」を見てください。
困ったら、まず Tailscale が接続済みか確認してください。
```

## 丁寧版テンプレート

メールや紙の案内文に近い形で送る場合の例です。

```text
タブレットで口腔機能・栄養評価システムを使う方へのご案内です。

このシステムは、先に Tailscale を接続してから開きます。
タブレットでは Windows 用 launcher は使いません。

手順
1. App Store または Google Play で Tailscale をインストールします。
2. Tailscale を開き、管理者から案内した方法でサインインします。
3. 接続済みになったら、Safari または Chrome で次の URL を開きます。
https://diskstation.tail632bc4.ts.net/

うまく開かない場合
1. 先に Tailscale アプリが接続済みか確認してください。
2. 接続できていない場合は、Tailscale を開き直してください。
3. それでも難しい場合は管理者へ連絡してください。
```

## 管理者メモ

1. タブレット利用者には `TailscaleClientLauncher.cmd` 一式は不要です。
2. 初心者向けには、URL だけでなく [TAILSCALE_TABLET_QR_SHEET_JA.html](TAILSCALE_TABLET_QR_SHEET_JA.html) を紙で配るほうが伝わりやすくなります。
3. パスワード運用を残している場合は、その案内文だけ別で追記してください。
4. URL が変わった場合は、このテンプレート内の URL をまとめて差し替えてから送ってください。