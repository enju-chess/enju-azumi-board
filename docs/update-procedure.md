# 週次更新の手順（Claude用）

毎週の自動実行で、この手順に沿って `data/board.json` を作り直す。

## 0. 準備
- `config/favorites.json`（好み・ルール）と `config/sources.json`（情報源）を読む
- 今の `data/board.json` を読み、形式（キー名・構造）をそのまま踏襲する
- 対象期間：実行日から14日後まで

## 1. 録画候補（recording）
- お気に入りの脚本家・俳優について、期間内に放送がある地上波・BSの連続ドラマや特番を探す
  - 見られるのは `favorites.json` の `receivable` にある地上波・BSだけ。CS・WOWOWなど有料チャンネルの番組は載せない
  - 番組一覧サイトは主要キャストしか載らないので、人物名でも検索して脇役出演を拾う
- 新番組の初回（is_premiere: true）を優先し、続いている番組は slot に「毎週◯曜」と書く
- `kind`: favorite / local_interest（長崎・佐賀が舞台など）/ discovery
- **discovery は毎週1本だけ**：好みと関係なく、その週に話題の番組を選ぶ。前週と同じものは避ける
- いつもの番組（regular_programs）は、期間内に放送がある回だけ放送日を入れる。なければ status に「今週の放送なし」

- 写真：クランクイン！の作品ページ（crank-in.net/drama/…）のog:image（メイン画像）URLを `image` に入れる。放送局の公式サイトは取得できないので使わない

- 概要：各番組の `summary` に、作品ページの「みどころ」などから2〜3文の紹介文を入れる（配信・地元イベントも同様。地元は時間・料金など行く判断に役立つ情報を含める）

## 2. 配信（streaming）
- 写真：アニメはクランクイン！の作品ページ（crank-in.net/animation/…）のog:imageを使う
- Prime Video（契約中）：新作アニメ、お気に入りの人の作品
- その他のサービスは subscribed: false で、お気に入りの人の作品だけ「参考」として載せる

## 3. 映画（movies）
- 長崎市内の映画館の上映作品のうち、お気に入りの人が出ている作品

## 4. 長崎・佐賀（local）
- 件数は10〜15件、日付順
- **グルメ（category: food）は約半分**。残りは祭り・展示・音楽・伝統芸能・自然など幅広く
- 普段選ばないジャンルを毎回1〜2件混ぜる
- 日帰り（category: day_trip）は毎回2件：`favorites.json` の `day_trip.sightseeing` から1件、`day_trip.theme_parks` から1件（genre はそれぞれ「日帰り定番」「テーマパーク」）。`visited` の場所と前週と同じ場所は避ける。
- 情報源は `config/sources.json` の順に確認。写真は各イベント個別ページのメイン画像URLを `image` に入れ、取れなければ null
- 期間外でも大型イベントは `coming_soon` に入れる

## 5. 確認と保存
- 書いた事実（日付・場所・出演者）は必ず出典ページで確認し、`source` にURLを入れる。確認できないものは載せない
- JSONとして正しく読めるか確認する
- `updated_at` と `period` を更新
- コミットして main にプッシュ。コミットメッセージは「週次更新 YYYY-MM-DD」
