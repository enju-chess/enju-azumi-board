"""
売買シグナルのバックテスト（底からの反転 / 勢いのある上昇 → デッドクロスで売り）

■ 使い方（M1 Mac のターミナル）
    source ~/Documents/Python/.venv/bin/activate
    pip install yfinance pandas xlrd
    python backtest_signals.py                  # 東証の規模別に各80銘柄・過去10年
    python backtest_signals.py --per-tier 150   # 銘柄数を増やす（時間がかかる）
    python backtest_signals.py --extra "GC=F,BTC-USD,AAPL,NVDA,MSFT"   # 金・BTC・米国株も追加
    python backtest_signals.py --demo           # ダミーデータで動作確認だけ

■ 結果
    results/report.html   … スマホでも見やすい集計表
    results/trades.csv    … 全取引の明細
    results/summary.csv   … 集計の生データ

■ ルール（すべて終値ベースで判定し、翌営業日の始値で売買）
  [反転] 前提: 過去1年の6割以上の日で終値が200日線の下（＝長く低迷）
     B1 ゴールデンクロス（25日線が75日線を上抜け）
     B2 終値が200日線を上抜け
     B3 出来高急増（20日平均の2倍以上）で陽線
     B4 ボックス上放れ（終値が過去60日の最高値を更新）
     → 直近5日以内に起きた条件の数がスコア
  [勢い]
     M1 パーフェクトオーダー（5日>25日>75日、3本とも上向き）
     M2 52週高値更新（直近5日以内）
     M3 ADX25以上かつ+DI>-DI（上昇トレンドが強い）
     M4 5日平均出来高が60日平均の1.5倍以上
     → 当日満たしている条件の数がスコア
  [売り] 5日線が25日線を終値ベースで下回った日（デッドクロス）
         ＋オプションで損切り（買値から終値で-8%）、最長保有250日
  手数料・スリッページとして片道0.1%を差し引き
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

JPX_LIST_URL = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
                "tvdivq0000001vg2-att/data_j.xls")
COST = 0.001        # 片道コスト
MAX_HOLD = 250
STOP_CONFIGS = {"損切りなし": None, "損切り-8%": 0.08}
TIER_ORDER = ["大型(TOPIX100)", "中型(Mid400)", "小型1(Small1)", "小型2(Small2)",
              "TOPIX外(新興など)", "海外・商品"]


# ---------------------------------------------------------------- 銘柄リスト
def load_universe(per_tier, seed=0):
    df = pd.read_excel(JPX_LIST_URL, dtype=str)
    df = df[df["市場・商品区分"].str.contains("内国株式", na=False)]
    tier_map = {
        "TOPIX Core30": "大型(TOPIX100)", "TOPIX Large70": "大型(TOPIX100)",
        "TOPIX Mid400": "中型(Mid400)",
        "TOPIX Small 1": "小型1(Small1)", "TOPIX Small 2": "小型2(Small2)",
    }
    df["tier"] = df["規模区分"].map(tier_map).fillna("TOPIX外(新興など)")
    out = []
    for tier, g in df.groupby("tier"):
        g = g.sample(n=min(per_tier, len(g)), random_state=seed)
        for _, r in g.iterrows():
            out.append((f"{r['コード']}.T", r["銘柄名"], tier))
    return out


def download(tickers, years):
    import yfinance as yf
    data = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        raw = yf.download(chunk, period=f"{years}y", auto_adjust=True,
                          group_by="ticker", threads=True, progress=True)
        for t in chunk:
            try:
                d = raw[t] if len(chunk) > 1 else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(d) > 300:
                    data[t] = d
            except Exception:
                pass
    return data


# ---------------------------------------------------------------- ダミーデータ
def demo_data(n_tickers=40, days=2500, seed=1):
    rng = np.random.default_rng(seed)
    universe, data = [], {}
    idx = pd.bdate_range("2016-01-01", periods=days)
    for k in range(n_tickers):
        drift = np.repeat(rng.normal(0, 0.002, days // 120 + 1), 120)[:days]
        ret = drift + rng.normal(0, 0.018, days)
        close = 1000 * np.exp(np.cumsum(ret))
        open_ = close * np.exp(rng.normal(0, 0.005, days))
        high = np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.008, days)))
        low = np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.008, days)))
        vol = rng.lognormal(12, 0.4, days) * (1 + 3 * (ret > 0.03))
        t = f"DEMO{k}"
        data[t] = pd.DataFrame({"Open": open_, "High": high, "Low": low,
                                "Close": close, "Volume": vol}, index=idx)
        universe.append((t, t, TIER_ORDER[k % 4]))
    return universe, data


# ---------------------------------------------------------------- 指標
def adx(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, df.index).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, df.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean(), pdi, mdi


def recent(cond, days=5):
    return cond.astype(int).rolling(days, min_periods=1).max().astype(bool)


def signals(df):
    c, v = df["Close"], df["Volume"]
    ma5, ma25, ma75, ma200 = (c.rolling(n).mean() for n in (5, 25, 75, 200))
    vol20 = v.rolling(20).mean().shift(1)

    # 反転
    slump = (c < ma200).astype(float).rolling(250).mean().shift(1) >= 0.6
    b1 = (ma25 > ma75) & (ma25.shift() <= ma75.shift())
    b2 = (c > ma200) & (c.shift() <= ma200.shift())
    b3 = (v > 2 * vol20) & (c > c.shift())
    b4 = c > c.rolling(60).max().shift(1)
    bottom = sum(recent(x).astype(int) for x in (b1, b2, b3, b4))
    bottom = bottom.where(slump, 0)

    # 勢い
    m1 = (ma5 > ma25) & (ma25 > ma75) & (ma5 > ma5.shift(5)) & \
         (ma25 > ma25.shift(5)) & (ma75 > ma75.shift(5))
    m2 = recent(c > c.rolling(250).max().shift(1))
    a, pdi, mdi = adx(df)
    m3 = (a >= 25) & (pdi > mdi)
    m4 = v.rolling(5).mean() > 1.5 * v.rolling(60).mean().shift(5)
    momentum = sum(x.astype(int) for x in (m1, m2, m3, m4))

    dead = (ma5 < ma25) & (ma5.shift() >= ma25.shift())
    valid = ma200.notna() & ma75.notna()
    return (bottom.where(valid, 0).astype(int),
            momentum.where(valid, 0).astype(int),
            dead.fillna(False))


# ---------------------------------------------------------------- 売買シミュレーション
def simulate(df, score, dead, k, stop):
    """score が k 以上に上がった日の翌日始値で買い、売り条件の翌日始値で売る"""
    o, c = df["Open"].values, df["Close"].values
    entry_sig = ((score >= k) & (score.shift(fill_value=0) < k)).values
    dead = dead.values
    n, i, trades = len(df), 0, []
    while i < n - 1:
        if not entry_sig[i]:
            i += 1
            continue
        buy_i = i + 1
        buy = o[buy_i] * (1 + COST)
        j, reason = buy_i, "期間終了"
        while j < n - 1:
            if dead[j] and j > buy_i:
                reason = "デッドクロス"; break
            if stop and c[j] <= buy * (1 - stop):
                reason = "損切り"; break
            if j - buy_i >= MAX_HOLD:
                reason = "最長保有"; break
            j += 1
        sell_i = min(j + 1, n - 1)
        sell = o[sell_i] * (1 - COST)
        trades.append((df.index[buy_i], df.index[sell_i], sell / buy - 1,
                       sell_i - buy_i, reason, buy_i))
        i = sell_i
    return trades


def baseline(c, h, cache):
    """シグナルを使わず、適当な日に買って同じ日数持った場合の平均リターン"""
    if h not in cache:
        cache[h] = float((c.shift(-h) / c - 1).mean()) - 2 * COST
    return cache[h]


# ---------------------------------------------------------------- 集計
def summarize(tr):
    rows = []
    keys = ["戦略", "損切り", "スコア", "規模"]
    for key, g in tr.groupby(keys):
        r = g["リターン"]
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rows.append(dict(zip(keys, key), 取引数=len(g),
                         勝率=(r > 0).mean(), 平均損益=r.mean(), 中央値=r.median(),
                         平均保有日数=g["保有日数"].mean(),
                         PF=gain / loss if loss > 0 else np.nan,
                         適当に買った場合=g["比較"].mean(),
                         上乗せ=(r - g["比較"]).mean()))
    return pd.DataFrame(rows)


def pct(x):
    return "" if pd.isna(x) else f"{x*100:+.1f}%"


def html_report(s, tr, n_stocks, period):
    css = """body{font-family:-apple-system,'Hiragino Sans',sans-serif;margin:16px;
    color:#222;background:#fff}h1{font-size:20px}h2{font-size:17px;margin-top:28px}
    h3{font-size:15px;margin:18px 0 6px}.wrap{overflow-x:auto}
    table{border-collapse:collapse;font-size:13px;white-space:nowrap}
    th,td{border:1px solid #ddd;padding:4px 7px;text-align:right}th{background:#f3f3f3}
    td:first-child,th:first-child{text-align:left}.p{color:#c62828}.n{color:#1565c0}
    .note{font-size:13px;color:#555;line-height:1.6}
    @media(prefers-color-scheme:dark){body{background:#111;color:#ddd}th{background:#222}
    th,td{border-color:#333}.note{color:#aaa}}"""
    parts = [f"<html><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>シグナル検証</title>"
             f"<style>{css}</style></head><body><h1>シグナルのバックテスト結果</h1>",
             f"<p class='note'>対象 {n_stocks} 銘柄 / 期間 {period} / 取引総数 {len(tr)}<br>"
             "<b>上乗せ</b>＝シグナルなしで適当な日に買い、同じ日数持った場合と比べて1回あたり何%良かったか。"
             "ここがプラスで取引数が十分（目安50回以上）なら、シグナルに意味がある可能性があります。</p>"]
    for strat in ["反転", "勢い"]:
        for stop in STOP_CONFIGS:
            sub = s[(s["戦略"] == strat) & (s["損切り"] == stop)]
            if sub.empty:
                continue
            parts.append(f"<h2>{strat}シグナル（{stop}）</h2>")
            for metric in ["上乗せ", "平均損益", "勝率", "取引数"]:
                pv = sub.pivot_table(index="スコア", columns="規模", values=metric)
                pv = pv[[t for t in TIER_ORDER if t in pv.columns]]
                parts.append(f"<h3>{metric}</h3><div class='wrap'><table><tr><th>条件数</th>"
                             + "".join(f"<th>{t}</th>" for t in pv.columns) + "</tr>")
                for k, row in pv.iterrows():
                    cells = []
                    for x in row:
                        if metric == "取引数":
                            cells.append(f"<td>{'' if pd.isna(x) else int(x)}</td>")
                        elif metric == "勝率":
                            cells.append(f"<td>{'' if pd.isna(x) else f'{x*100:.0f}%'}</td>")
                        else:
                            cls = "" if pd.isna(x) else ("p" if x > 0 else "n")
                            cells.append(f"<td class='{cls}'>{pct(x)}</td>")
                    parts.append(f"<tr><td>{k}つ以上</td>{''.join(cells)}</tr>")
                parts.append("</table></div>")
    ex = tr.groupby(["戦略", "売却理由"]).size().unstack(fill_value=0)
    parts.append("<h2>売却理由の内訳</h2><div class='wrap'>" + ex.to_html() + "</div>")
    parts.append("<p class='note'>注意: 銘柄の規模区分は現在のもの。上場廃止銘柄は含まれないため、"
                 "結果はやや良く出る傾向があります（生存者バイアス）。</p></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tier", type=int, default=80)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--extra", default="", help="追加銘柄（カンマ区切り）例: GC=F,BTC-USD,AAPL")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    if args.demo:
        universe, data = demo_data()
    else:
        print("東証の銘柄リストを取得中…")
        universe = load_universe(args.per_tier)
        universe += [(t.strip(), t.strip(), "海外・商品")
                     for t in args.extra.split(",") if t.strip()]
        print(f"{len(universe)} 銘柄の株価を取得中…")
        data = download([u[0] for u in universe], args.years)
    tier_of = {t: tier for t, _, tier in universe}
    name_of = {t: nm for t, nm, _ in universe}

    rows = []
    for t, df in data.items():
        bottom, momentum, dead = signals(df)
        cache = {}
        for strat, score in (("反転", bottom), ("勢い", momentum)):
            for stop_name, stop in STOP_CONFIGS.items():
                for k in (1, 2, 3, 4):
                    for b, s, r, h, why, _ in simulate(df, score, dead, k, stop):
                        rows.append(dict(銘柄=t, 銘柄名=name_of[t], 規模=tier_of[t],
                                         戦略=strat, 損切り=stop_name, スコア=k,
                                         買い日=b.date(), 売り日=s.date(), リターン=r,
                                         保有日数=h, 売却理由=why,
                                         比較=baseline(df["Close"], h, cache)))
    if not rows:
        sys.exit("取引が1件もありませんでした。")
    tr = pd.DataFrame(rows)
    s = summarize(tr)

    os.makedirs(args.out, exist_ok=True)
    tr.to_csv(f"{args.out}/trades.csv", index=False, encoding="utf-8-sig")
    s.to_csv(f"{args.out}/summary.csv", index=False, encoding="utf-8-sig")
    first = min(d.index[0] for d in data.values()).date()
    last = max(d.index[-1] for d in data.values()).date()
    with open(f"{args.out}/report.html", "w", encoding="utf-8") as f:
        f.write(html_report(s, tr, len(data), f"{first}〜{last}"))
    print(f"\n完了: {args.out}/report.html を開いてください")
    show = s[(s["損切り"] == "損切り-8%")][["戦略", "スコア", "規模", "取引数", "勝率", "平均損益", "上乗せ"]]
    with pd.option_context("display.max_rows", 200, "display.width", 200):
        print(show.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
