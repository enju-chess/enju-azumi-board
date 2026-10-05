# ふたりのテレビ情報板

夫婦で楽しく暮らすための情報を集めて、ブラビア（Google TV）に表示するための置き場です。

## 仕組み

1. 週1回、Claude が情報を集めて `data/board.json` を更新する
2. テレビの自作アプリが `board.json` を読んで表示する（アプリ画面＋スクリーンセーバー）

## ファイル

- `config/favorites.json` … お気に入りの脚本家・俳優・いつもの番組、契約中の配信サービス
- `data/board.json` … テレビに表示するデータ（自動更新）

## 投資シグナル（invest/）

- `invest/backtest_signals.py` … 売買シグナル（底からの反転・勢いのある上昇→デッドクロスで売り）のバックテスト
- GitHub の Actions タブ →「投資シグナルのバックテスト」→ Run workflow で実行。結果は backtest-results としてダウンロードできる
