"""
売買シグナルのバックテスト v2
（底からの反転 / 勢いのある上昇 → 複数の売り方を比較）

■ 使い方
    pip install yfinance pandas xlrd openpyxl lxml
    python backtest_signals.py                    # 日本株 規模別各80銘柄 + 米国S&P500 100銘柄
    python backtest_signals.py --per-tier 150 --us 200
    python backtest_signals.py --extra "GC=F,BTC-USD"   # 金・BTCなどを個別に追加
    python backtest_signals.py --demo             # ダミーデータで動作確認

■ 結果: results/report.html, results/trades.csv, results/summary.csv, results/forward.csv

■ ルール（終値ベースで判定し、翌営業日の始値で売買。片道0.1%のコストを差し引き）
  [反転] 前提: 過去1年の6割以上の日で終値が200日線の下（＝長く低迷）
     B1 ゴールデンクロス（25日線が75日線を上抜け）
     B2 終値が200日線を上抜け
     B3 出来高急増（20日平均の2倍以上）で陽線
     B4 ボックス上放れ（終値が過去60日の最高値を更新）
     → 直近5日以内に起きた条件の数がスコア
  [勢い]
     M1 パーフェクトオーダー（5日>25日>75日、3本とも上向き）
     M2 52週高値更新（直近5日以内）
     M3 ADX25以上かつ+DI>-DI
     M4 5日平均出来高が60日平均の1.5倍以上
     → 当日満たしている条件の数がスコア
  [売り方]（どれも最長250日で強制売却）
     A 5日線が25日線を下回る（最初のルール）
     B 25日線が75日線を下回る
     C B＋損切り（買値から-8%）
     D トレーリングストップ（買ってからの最高値から-10%）
  [買いの質] 売り方を考えず、シグナルの翌日に買って20日・60日持ち続けた場合
"""

import argparse
import io
import os
import re
import sys
import urllib.request

import numpy as np
import pandas as pd

JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
SP500_PAGE = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
COST = 0.001
MAX_HOLD = 250
EXITS = {
    "A 5日/25日線クロス": dict(fast=5, slow=25, stop=None, trail=None),
    "B 25日/75日線クロス": dict(fast=25, slow=75, stop=None, trail=None),
    "C 25/75クロス+損切り8%": dict(fast=25, slow=75, stop=0.08, trail=None),
    "D 高値から-10%": dict(fast=None, slow=None, stop=None, trail=0.10),
}
HORIZONS = (20, 60)
JP_TIERS = ["大型(TOPIX100)", "中型(Mid400)", "小型1(Small1)", "小型2(Small2)", "TOPIX外(新興など)"]
TIER_ORDER = JP_TIERS + ["日本株 全体", "米国(S&P500)", "その他(個別指定)"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read()


# ---------------------------------------------------------------- 銘柄リスト
def load_japan(per_tier, seed=0):
    page = get(JPX_PAGE).decode("utf-8", "ignore")
    link = re.search(r'href="([^"]*data_j\.xlsx?)"', page).group(1)
    url = link if link.startswith("http") else "https://www.jpx.co.jp" + link
    print("銘柄リスト:", url)
    df = pd.read_excel(io.BytesIO(get(url)), dtype=str)
    df = df[df["市場・商品区分"].str.contains("内国株式", na=False)]
    tier_map = {
        "TOPIX Core30": JP_TIERS[0], "TOPIX Large70": JP_TIERS[0],
        "TOPIX Mid400": JP_TIERS[1], "TOPIX Small 1": JP_TIERS[2], "TOPIX Small 2": JP_TIERS[3],
    }
    df["tier"] = df["規模区分"].map(tier_map).fillna(JP_TIERS[4])
    out = []
    for tier, g in df.groupby("tier"):
        for _, r in g.sample(n=min(per_tier, len(g)), random_state=seed).iterrows():
            out.append((f"{r['コード']}.T", r["銘柄名"], tier))
    return out


def load_us(n, seed=0):
    if n <= 0:
        return []
    tables = pd.read_html(io.StringIO(get(SP500_PAGE).decode("utf-8")))
    sp = next(t for t in tables if "Symbol" in t.columns)
    sp = sp.sample(n=min(n, len(sp)), random_state=seed)
    for s_, sub in zip(sp["Symbol"], sp["GICS Sub-Industry"]):
        if "Semiconductor" in str(sub):
            SEMI_US.add(s_.replace(".", "-"))
    return [(s.replace(".", "-"), name, "米国(S&P500)")
            for s, name in zip(sp["Symbol"], sp["Security"])]


# 日本の主な半導体関連（製造装置・材料・メモリ・パッケージ基板を含む）
SEMI_JP = {
    "8035", "6857", "6920", "7735", "6146", "6526", "6723", "4063", "3436", "285A",
    "6963", "7729", "6323", "6890", "4062", "4004", "4186", "6254", "6315", "6728",
    "6871", "6855", "6525", "4970", "5384", "6627", "4369", "6707", "3445", "6266",
    "4980", "7741", "6588", "5344", "6699", "6787", "4975", "6235", "7701", "6284",
}
SEMI_US = set()


def find_semis(tickers):
    """半導体関連の銘柄を判定（日本: 一覧＋Yahooの業種、米国: S&P500のGICS分類）"""
    import yfinance as yf
    semis = {t for t in tickers if t in SEMI_US or t.removesuffix(".T") in SEMI_JP}
    for t in tickers:
        if not t.endswith(".T") or t in semis:
            continue
        try:
            ind = (yf.Ticker(t).info or {}).get("industry", "")
            if "Semiconductor" in ind:
                semis.add(t)
        except Exception:
            pass
    return semis


def download(tickers, years):
    import yfinance as yf
    data = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        raw = yf.download(chunk, period=f"{years}y", auto_adjust=True,
                          group_by="ticker", threads=True, progress=False)
        for t in chunk:
            try:
                d = raw[t] if len(chunk) > 1 else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
                d = d[(d["Close"] > 0) & (d["Open"] > 0)]
                if len(d) > 300:
                    data[t] = d
            except Exception:
                pass
    return data


def demo_data(n_tickers=30, days=2500, seed=1):
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
        universe.append((t, t, (JP_TIERS + ["米国(S&P500)"])[k % 6]))
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
    ma = {n: c.rolling(n).mean() for n in (5, 25, 75, 200)}
    vol20 = v.rolling(20).mean().shift(1)

    slump = (c < ma[200]).astype(float).rolling(250).mean().shift(1) >= 0.6
    b1 = (ma[25] > ma[75]) & (ma[25].shift() <= ma[75].shift())
    b2 = (c > ma[200]) & (c.shift() <= ma[200].shift())
    b3 = (v > 2 * vol20) & (c > c.shift())
    b4 = c > c.rolling(60).max().shift(1)
    bottom = sum(recent(x).astype(int) for x in (b1, b2, b3, b4)).where(slump, 0)

    m1 = (ma[5] > ma[25]) & (ma[25] > ma[75]) & (ma[5] > ma[5].shift(5)) & \
         (ma[25] > ma[25].shift(5)) & (ma[75] > ma[75].shift(5))
    m2 = recent(c > c.rolling(250).max().shift(1))
    a, pdi, mdi = adx(df)
    m3 = (a >= 25) & (pdi > mdi)
    m4 = v.rolling(5).mean() > 1.5 * v.rolling(60).mean().shift(5)
    momentum = sum(x.astype(int) for x in (m1, m2, m3, m4))

    valid = ma[200].notna()
    return bottom.where(valid, 0).astype(int), momentum.where(valid, 0).astype(int), ma


def entries(score, k):
    return ((score >= k) & (score.shift(fill_value=0) < k)).values


# ---------------------------------------------------------------- 売買シミュレーション
def simulate(df, entry_sig, ma, rule):
    o, c = df["Open"].values, df["Close"].values
    dead = None
    if rule["fast"]:
        f, s = ma[rule["fast"]], ma[rule["slow"]]
        dead = ((f < s) & (f.shift() >= s.shift())).fillna(False).values
    n, i, trades = len(df), 0, []
    while i < n - 1:
        if not entry_sig[i]:
            i += 1
            continue
        b = i + 1
        buy = o[b] * (1 + COST)
        peak, j, reason = c[b], b, "期間終了"
        while j < n - 1:
            peak = max(peak, c[j])
            if dead is not None and dead[j] and j > b:
                reason = "クロス"; break
            if rule["stop"] and c[j] <= buy * (1 - rule["stop"]):
                reason = "損切り"; break
            if rule["trail"] and c[j] <= peak * (1 - rule["trail"]):
                reason = "高値から下落"; break
            if j - b >= MAX_HOLD:
                reason = "最長保有"; break
            j += 1
        s = min(j + 1, n - 1)
        trades.append((df.index[b], df.index[s], o[s] * (1 - COST) / buy - 1, s - b, reason))
        i = s
    return trades


def baseline(c, h, cache):
    if h not in cache:
        cache[h] = float((c.shift(-h) / c - 1).mean()) - 2 * COST
    return cache[h]


# ---------------------------------------------------------------- 集計
def add_overall(df):
    jp = df[df["規模"].isin(JP_TIERS)].copy()
    jp["規模"] = "日本株 全体"
    return pd.concat([df, jp], ignore_index=True)


def summarize(tr):
    rows, keys = [], ["戦略", "売り方", "スコア", "規模"]
    for key, g in tr.groupby(keys):
        r = g["リターン"]
        gain, loss = r[r > 0].sum(), -r[r < 0].sum()
        rows.append(dict(zip(keys, key), 取引数=len(g), 勝率=(r > 0).mean(),
                         平均損益=r.mean(), 中央値=r.median(), 平均保有日数=g["保有日数"].mean(),
                         PF=gain / loss if loss > 0 else np.nan,
                         上乗せ=(r - g["比較"]).mean()))
    return pd.DataFrame(rows)


def summarize_forward(fw):
    rows = []
    for key, g in fw.groupby(["戦略", "スコア", "規模"]):
        row = dict(zip(["戦略", "スコア", "規模"], key), 回数=len(g))
        for h in HORIZONS:
            r = g[f"r{h}"].dropna()
            row[f"{h}日 勝率"] = (r > 0).mean()
            row[f"{h}日 上乗せ"] = (r - g.loc[r.index, f"b{h}"]).mean()
        rows.append(row)
    return pd.DataFrame(rows)


CSS = """body{font-family:-apple-system,'Hiragino Sans',sans-serif;margin:16px;color:#222;
background:#fff;line-height:1.5}h1{font-size:20px}h2{font-size:17px;margin-top:30px;
border-bottom:2px solid #ccc;padding-bottom:4px}h3{font-size:15px;margin:18px 0 6px}
.wrap{overflow-x:auto}table{border-collapse:collapse;font-size:13px;white-space:nowrap}
th,td{border:1px solid #ddd;padding:4px 7px;text-align:right}th{background:#f3f3f3}
td:first-child,th:first-child{text-align:left}.p{color:#c62828}.n{color:#1565c0}
.s{color:#888;font-size:11px}.note{font-size:13px;color:#555}
@media(prefers-color-scheme:dark){body{background:#111;color:#ddd}th{background:#222}
th,td{border-color:#333}.note{color:#aaa}}"""


def cell(val, n=None, win=None):
    if pd.isna(val):
        return "<td></td>"
    cls = "p" if val > 0 else "n"
    sub = ""
    if n is not None:
        sub = f"<br><span class='s'>{int(n)}回"
        sub += f" 勝{win*100:.0f}%" if win is not None and not pd.isna(win) else ""
        sub += "</span>"
    return f"<td><span class='{cls}'>{val*100:+.1f}%</span>{sub}</td>"


def tiers_in(df):
    return [t for t in TIER_ORDER if t in set(df["規模"])]


def html_report(s, f, n_stocks, period):
    p = [f"<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
         f"initial-scale=1'><title>シグナル検証 v2</title><style>{CSS}</style></head><body>",
         "<h1>シグナルのバックテスト結果 v2</h1>",
         f"<p class='note'>対象 {n_stocks} 銘柄 / 期間 {period}<br>"
         "数字はすべて<b>上乗せ</b>＝シグナルを使わずに適当な日に買い、同じ日数持った場合と比べて"
         "1回あたり何%良かったか。赤がプラス、青がマイナス。下の小さい字は取引回数と勝率。</p>"]

    p.append("<h2>① 買いの質（売り方を考えず、決まった日数持った場合）</h2>")
    for strat in ["反転", "勢い"]:
        sub = f[f["戦略"] == strat]
        cols = tiers_in(sub)
        p.append(f"<h3>{strat}シグナル</h3><div class='wrap'><table><tr><th>条件数</th><th>保有</th>"
                 + "".join(f"<th>{t}</th>" for t in cols) + "</tr>")
        for k in (1, 2, 3, 4):
            for h in HORIZONS:
                row = [f"<tr><td>{k}つ以上</td><td>{h}日</td>"]
                for t in cols:
                    x = sub[(sub["スコア"] == k) & (sub["規模"] == t)]
                    row.append(cell(x[f"{h}日 上乗せ"].iloc[0], x["回数"].iloc[0], x[f"{h}日 勝率"].iloc[0])
                               if len(x) else "<td></td>")
                p.append("".join(row) + "</tr>")
        p.append("</table></div>")

    p.append("<h2>② 売り方の比較（実際に売買した場合）</h2>")
    for strat in ["反転", "勢い"]:
        for k in (1, 2, 3):
            sub = s[(s["戦略"] == strat) & (s["スコア"] == k)]
            cols = tiers_in(sub)
            p.append(f"<h3>{strat}シグナル・条件{k}つ以上</h3><div class='wrap'><table><tr><th>売り方</th>"
                     + "".join(f"<th>{t}</th>" for t in cols) + "<th>平均保有</th></tr>")
            for ex in EXITS:
                row = [f"<tr><td>{ex}</td>"]
                for t in cols:
                    x = sub[(sub["売り方"] == ex) & (sub["規模"] == t)]
                    row.append(cell(x["上乗せ"].iloc[0], x["取引数"].iloc[0], x["勝率"].iloc[0])
                               if len(x) else "<td></td>")
                hold = sub[(sub["売り方"] == ex) & (sub["規模"] == "日本株 全体")]["平均保有日数"]
                row.append(f"<td>{hold.iloc[0]:.0f}日</td>" if len(hold) else "<td></td>")
                p.append("".join(row) + "</tr>")
            p.append("</table></div>")
    p.append("<p class='note'>注意: 銘柄は現在の上場銘柄・現在のS&P500構成銘柄から選んでいるため、"
             "途中で上場廃止・指数除外された銘柄が含まれず、結果はやや良く出ます（生存者バイアス）。</p>"
             "</body></html>")
    return "".join(p)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tier", type=int, default=80)
    ap.add_argument("--us", type=int, default=100, help="S&P500から選ぶ銘柄数")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--extra", default="", help="個別に追加する銘柄（カンマ区切り）")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--exclude-semis", action="store_true", help="半導体関連を除く")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    if args.demo:
        universe, data = demo_data()
    else:
        print("銘柄リストを取得中…")
        universe = load_japan(args.per_tier)
        try:
            universe += load_us(args.us)
        except Exception as e:
            print("S&P500リストの取得に失敗:", e)
        universe += [(t.strip(), t.strip(), "その他(個別指定)")
                     for t in args.extra.split(",") if t.strip()]
        print(f"{len(universe)} 銘柄の株価を取得中…")
        data = download([u[0] for u in universe], args.years)
        if args.exclude_semis:
            semis = find_semis(list(data))
            names = {t: n for t, n, _ in universe}
            print(f"半導体関連として除外: {len(semis)} 銘柄")
            for t in sorted(semis):
                print("  ", t, names.get(t, ""))
            data = {t: d for t, d in data.items() if t not in semis}
    tier_of = {t: tier for t, _, tier in universe}
    name_of = {t: nm for t, nm, _ in universe}

    trades, fwd = [], []
    for t, df in data.items():
        bottom, momentum, ma = signals(df)
        cache = {}
        o, c = df["Open"], df["Close"]
        r_h = {h: (c.shift(-h) / o.shift(-1) * (1 - COST) / (1 + COST) - 1).values for h in HORIZONS}
        for strat, score in (("反転", bottom), ("勢い", momentum)):
            for k in (1, 2, 3, 4):
                sig = entries(score, k)
                for i in np.flatnonzero(sig[:-1]):
                    row = dict(銘柄=t, 規模=tier_of[t], 戦略=strat, スコア=k, 日付=df.index[i].date())
                    for h in HORIZONS:
                        row[f"r{h}"] = r_h[h][i]
                        row[f"b{h}"] = baseline(c, h, cache)
                    fwd.append(row)
                if k == 4:
                    continue  # 実売買のシミュレーションは条件3つ以上まで
                for ex, rule in EXITS.items():
                    for b, s_, r, h, why in simulate(df, sig, ma, rule):
                        trades.append(dict(銘柄=t, 銘柄名=name_of[t], 規模=tier_of[t], 戦略=strat,
                                           売り方=ex, スコア=k, 買い日=b.date(), 売り日=s_.date(),
                                           リターン=r, 保有日数=h, 売却理由=why,
                                           比較=baseline(c, h, cache)))
    if not trades:
        sys.exit("取引が1件もありませんでした。")
    tr, fw = add_overall(pd.DataFrame(trades)), add_overall(pd.DataFrame(fwd))
    s, f = summarize(tr), summarize_forward(fw)

    os.makedirs(args.out, exist_ok=True)
    tr[tr["規模"] != "日本株 全体"].to_csv(f"{args.out}/trades.csv", index=False, encoding="utf-8-sig")
    s.to_csv(f"{args.out}/summary.csv", index=False, encoding="utf-8-sig")
    f.to_csv(f"{args.out}/forward.csv", index=False, encoding="utf-8-sig")
    first = min(d.index[0] for d in data.values()).date()
    last = max(d.index[-1] for d in data.values()).date()
    with open(f"{args.out}/report.html", "w", encoding="utf-8") as fh:
        fh.write(html_report(s, f, len(data), f"{first}〜{last}"))
    print(f"完了: {args.out}/report.html")
    with pd.option_context("display.max_rows", 500, "display.width", 250):
        print(f.round(3).to_string(index=False))
        print(s[s["規模"].isin(["日本株 全体", "米国(S&P500)"])][
            ["戦略", "売り方", "スコア", "規模", "取引数", "勝率", "平均保有日数", "上乗せ"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
