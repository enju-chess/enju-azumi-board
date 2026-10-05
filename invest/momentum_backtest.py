"""
モメンタム（相対的な強さ）戦略のバックテスト

毎月末に「過去の上昇率」で銘柄を順位付けし、上位を持つ。翌月末に入れ替え。
売買は判断した翌営業日の終値で行う（片道0.1%のコストを差し引き）。

■ 比較する戦略（日本: TOPIX500 / 米国: S&P500 それぞれで実施）
  指数そのもの          … TOPIX連動ETF(1306) / SPY を買って持ち続ける
  全銘柄に均等投資      … 対象の全銘柄を毎月均等に持ち直す（銘柄選びをしない場合の基準）
  ① 12ヶ月モメンタム   … 過去12ヶ月（直近1ヶ月を除く）の上昇率 上位10銘柄
  ① 6ヶ月モメンタム    … 過去6ヶ月（直近1ヶ月を除く）の上昇率 上位10銘柄
  ② ①12ヶ月＋相場フィルター … 月末に指数が200日線より下なら全て売って現金
  ③ ①12ヶ月＋押し目買い    … 上位10銘柄を候補にし、終値が5日線を下回った翌日に買う

■ 使い方
  pip install yfinance pandas xlrd openpyxl lxml
  python momentum_backtest.py --years 12
  python momentum_backtest.py --demo
"""

import argparse
import io
import os
import re
import urllib.request

import numpy as np
import pandas as pd

JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
SP500_PAGE = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
COST = 0.001
TOP_N = 10
SKIP = 21  # 直近1ヶ月は除く


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read()


def load_japan():
    page = get(JPX_PAGE).decode("utf-8", "ignore")
    link = re.search(r'href="([^"]*data_j\.xlsx?)"', page).group(1)
    url = link if link.startswith("http") else "https://www.jpx.co.jp" + link
    df = pd.read_excel(io.BytesIO(get(url)), dtype=str)
    df = df[df["規模区分"].isin(["TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"])]
    for c, sec in zip(df["コード"], df["33業種区分"]):
        SECTOR[f"{c}.T"] = str(sec)
    return {f"{c}.T": n for c, n in zip(df["コード"], df["銘柄名"])}


def load_us():
    tables = pd.read_html(io.StringIO(get(SP500_PAGE).decode("utf-8")))
    sp = next(t for t in tables if "Symbol" in t.columns)
    for sym, sub, sec in zip(sp["Symbol"], sp["GICS Sub-Industry"], sp["GICS Sector"]):
        if "Semiconductor" in str(sub):
            SEMI_US.add(sym.replace(".", "-"))
        SECTOR[sym.replace(".", "-")] = str(sec)
    return {s.replace(".", "-"): n for s, n in zip(sp["Symbol"], sp["Security"])}


# 日本の主な半導体関連（製造装置・材料・メモリ・パッケージ基板を含む）
SEMI_JP = {
    "8035", "6857", "6920", "7735", "6146", "6526", "6723", "4063", "3436", "285A",
    "6963", "7729", "6323", "6890", "4062", "4004", "4186", "6254", "6315", "6728",
    "6871", "6855", "6525", "4970", "5384", "6627", "4369", "6707", "3445", "6266",
    "4980", "7741", "6588", "5344", "6699", "6787", "4975", "6235", "6284",
}
SEMI_US = set()
SECTOR = {}
# AIデータセンター向けの電線・電力設備など、業種分類では拾えないAI関連
AI_EXTRA = {"5801.T", "5802.T", "5803.T", "VRT", "BE", "VST", "CEG", "GEV", "NRG", "TLN"}
AI_SECTORS = ("電気機器", "情報", "Information Technology", "Communication Services")


def find_ai(tickers):
    """AI関連: 電機・情報通信（米国はIT・通信サービス）全体＋半導体関連＋電線・電力設備"""
    out = set(find_semis(tickers))
    for t in tickers:
        if t in AI_EXTRA or any(k in SECTOR.get(t, "") for k in AI_SECTORS):
            out.add(t)
    return out


def find_semis(tickers):
    import yfinance as yf
    semis = {t for t in tickers if t in SEMI_US or t.removesuffix(".T") in SEMI_JP}
    for t in tickers:
        if t.endswith(".T") and t not in semis:
            try:
                if "Semiconductor" in ((yf.Ticker(t).info or {}).get("industry") or ""):
                    semis.add(t)
            except Exception:
                pass
    return semis


def download(tickers, years):
    import yfinance as yf
    closes = []
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        raw = yf.download(chunk, period=f"{years}y", auto_adjust=True,
                          group_by="ticker", threads=True, progress=False)
        for t in chunk:
            try:
                s = (raw[t] if len(chunk) > 1 else raw)["Close"].rename(t)
                if s.notna().sum() > 300:
                    closes.append(s)
            except Exception:
                pass
    return pd.concat(closes, axis=1)


def demo_prices(n=120, days=3000, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-01", periods=days)
    mkt = rng.normal(0.0003, 0.01, days)
    cols = {}
    for k in range(n):
        drift = np.repeat(rng.normal(0, 0.0015, days // 150 + 1), 150)[:days]
        cols[f"D{k}"] = 1000 * np.exp(np.cumsum(mkt + drift + rng.normal(0, 0.015, days)))
    px = pd.DataFrame(cols, index=idx)
    px["INDEX"] = 1000 * np.exp(np.cumsum(mkt))
    return px, {c: c for c in px.columns}


# ---------------------------------------------------------------- 戦略
def month_ends(idx):
    s = pd.Series(idx, index=idx)
    return set(s.groupby([idx.year, idx.month]).max())


def momentum_rank(px, i, lookback):
    if i < lookback:
        return []
    past, recent = px.iloc[i - lookback], px.iloc[i - SKIP]
    m = (recent / past - 1).dropna()
    return list(m.sort_values(ascending=False).index[:TOP_N])


def run(px, stocks, index_t, kind, lookback=252):
    """日次で資産額を計算する。kind: index / equal / mom / mom_filter / mom_dip"""
    idx = px.index
    ends = month_ends(idx)
    ret = px.pct_change().fillna(0.0)
    ma5 = px.rolling(5).mean()
    ma200 = px[index_t].rolling(200).mean()
    hold = {}            # ticker -> 金額
    cash, curve = 1.0, []
    pending = None       # 翌日に実行する目標 {ticker: weight} または None
    candidates, dip_buy = [], []

    for i, d in enumerate(idx):
        # 1) 値動きを反映
        for t in hold:
            hold[t] *= 1 + ret.at[d, t]
        total = cash + sum(hold.values())

        # 2) 前日の判断を今日の終値で実行
        if pending is not None:
            new = {t: total * w for t, w in pending.items()}
            traded = sum(abs(new.get(t, 0) - hold.get(t, 0)) for t in set(new) | set(hold))
            total -= traded * COST
            hold = {t: total * w for t, w in pending.items()}
            cash = total - sum(hold.values())
            pending = None
        for t in dip_buy:  # 押し目買い
            if t not in hold and cash > 0:
                amt = min(cash, total / TOP_N)
                hold[t] = amt * (1 - COST)
                cash -= amt
        dip_buy = []

        # 3) 今日の終値で判断
        if kind == "index":
            if i == 0:
                pending = {index_t: 1.0}
        elif d in ends or i == 0:
            if kind == "equal":
                avail = [t for t in stocks if not np.isnan(px.at[d, t])]
                pending = {t: 1 / len(avail) for t in avail} if avail else {}
            else:
                top = momentum_rank(px[stocks], i, lookback)
                if kind == "mom_filter" and not (px.at[d, index_t] >= ma200.iloc[i]):
                    top = []
                if kind == "mom_dip":
                    candidates = top
                    keep = {t: v for t, v in hold.items() if t in top}
                    tot = cash + sum(hold.values())
                    pending = {t: v / tot for t, v in keep.items()} if tot > 0 else {}
                elif top:
                    pending = {t: 1 / len(top) for t in top}
                else:
                    pending = {}
        if kind == "mom_dip":
            dip_buy = [t for t in candidates if t not in hold
                       and px.at[d, t] < ma5.at[d, t]]
        curve.append(total)
    return pd.Series(curve, index=idx)


def stats(curve):
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    r = curve.pct_change().dropna()
    dd = (curve / curve.cummax() - 1).min()
    yearly = curve.groupby(curve.index.year).last().pct_change()
    yearly.iloc[0] = curve.groupby(curve.index.year).last().iloc[0] / curve.iloc[0] - 1
    return dict(年率リターン=curve.iloc[-1] ** (1 / yrs) - 1, 最大下落=dd,
                年率の振れ幅=r.std() * np.sqrt(252), 最終資産=curve.iloc[-1]), yearly


# ---------------------------------------------------------------- レポート
COLORS = ["#888888", "#bbbbbb", "#d32f2f", "#f57c00", "#1976d2", "#388e3c"]
CSS = """body{font-family:-apple-system,'Hiragino Sans',sans-serif;margin:16px;color:#222;
background:#fff;line-height:1.5}h1{font-size:20px}h2{font-size:17px;margin-top:30px;
border-bottom:2px solid #ccc;padding-bottom:4px}.wrap{overflow-x:auto}
table{border-collapse:collapse;font-size:13px;white-space:nowrap}
th,td{border:1px solid #ddd;padding:4px 7px;text-align:right}th{background:#f3f3f3}
td:first-child,th:first-child{text-align:left}.p{color:#c62828}.n{color:#1565c0}
.note{font-size:13px;color:#555}.lg span{display:inline-block;margin-right:12px;font-size:12px}
svg{width:100%;height:auto;background:#fafafa}
@media(prefers-color-scheme:dark){body{background:#111;color:#ddd}th{background:#222}
th,td{border-color:#333}.note{color:#aaa}svg{background:#1a1a1a}}"""


def pc(x, bold=False):
    if pd.isna(x):
        return "<td></td>"
    return f"<td class='{'p' if x > 0 else 'n'}'>{x*100:+.1f}%</td>"


def svg_chart(curves):
    w, h, pad = 800, 360, 40
    logv = {k: np.log(v.resample("W").last()) for k, v in curves.items()}
    lo = min(v.min() for v in logv.values())
    hi = max(v.max() for v in logv.values())
    x0, x1 = min(v.index[0] for v in logv.values()), max(v.index[-1] for v in logv.values())
    span = (x1 - x0).days or 1
    out = [f"<svg viewBox='0 0 {w} {h}'>"]
    for mult in [0.5, 1, 2, 4, 8, 16]:
        if lo <= np.log(mult) <= hi:
            y = h - pad - (np.log(mult) - lo) / (hi - lo) * (h - 2 * pad)
            out.append(f"<line x1='{pad}' x2='{w-10}' y1='{y:.0f}' y2='{y:.0f}' stroke='#9995' />"
                       f"<text x='2' y='{y+4:.0f}' font-size='12' fill='#888'>{mult}倍</text>")
    for yr in range(x0.year + 1, x1.year + 1, 2):
        x = pad + (pd.Timestamp(yr, 1, 1) - x0).days / span * (w - pad - 10)
        out.append(f"<text x='{x:.0f}' y='{h-12}' font-size='12' fill='#888'>{yr}</text>")
    for (k, v), col in zip(logv.items(), COLORS):
        pts = " ".join(f"{pad + (d - x0).days / span * (w - pad - 10):.1f},"
                       f"{h - pad - (val - lo) / (hi - lo) * (h - 2 * pad):.1f}"
                       for d, val in v.items())
        out.append(f"<polyline fill='none' stroke='{col}' stroke-width='2' points='{pts}' />")
    out.append("</svg><div class='lg'>" + "".join(
        f"<span><b style='color:{c}'>━</b> {k}</span>" for k, c in zip(curves, COLORS)) + "</div>")
    return "".join(out)


def section(title, curves, picks, names):
    rows, years = [], {}
    for k, c in curves.items():
        s, y = stats(c)
        rows.append((k, s))
        years[k] = y
    p = [f"<h2>{title}</h2>", svg_chart(curves),
         "<div class='wrap'><table><tr><th>戦略</th><th>年率リターン</th><th>最大下落</th>"
         "<th>振れ幅(年)</th><th>100万円→</th></tr>"]
    for k, s in rows:
        p.append(f"<tr><td>{k}</td>{pc(s['年率リターン'])}{pc(s['最大下落'])}"
                 f"<td>{s['年率の振れ幅']*100:.0f}%</td><td>{s['最終資産']*100:.0f}万円</td></tr>")
    p.append("</table></div><h3>年ごとのリターン</h3><div class='wrap'><table><tr><th>年</th>"
             + "".join(f"<th>{k}</th>" for k in curves) + "</tr>")
    for yr in sorted(next(iter(years.values())).index, reverse=True):
        p.append(f"<tr><td>{yr}</td>" + "".join(pc(years[k].get(yr)) for k in curves) + "</tr>")
    p.append("</table></div>")
    p.append("<h3>現在の上位10銘柄（12ヶ月モメンタム）</h3><div class='wrap'><table>"
             "<tr><th>順位</th><th>銘柄</th><th>上昇率</th><th>株価</th></tr>")
    for n, (t, m, price) in enumerate(picks, 1):
        p.append(f"<tr><td>{n}</td><td>{names.get(t, t)} ({t})</td>{pc(m)}<td>{price:,.0f}</td></tr>")
    p.append("</table></div>")
    return "".join(p)


def clean(px):
    """データ不良（株式分割の未反映など）による1日±50%超の動きを除外して株価を作り直す"""
    raw = px.ffill()
    r = raw.pct_change()
    bad = r.abs() > 0.5
    print("除外した異常値:", int(bad.sum().sum()), "件",
          list(bad.sum()[bad.sum() > 0].index[:10]))
    r = r.mask(bad, 0.0)
    first = raw.apply(lambda c: c.first_valid_index())
    out = (1 + r.fillna(0)).cumprod()
    for c in out.columns:  # 上場前はNaNのまま、水準は元の初値に合わせる
        f = first[c]
        out.loc[:f, c] = np.nan if f is None else out.loc[:f, c]
        if f is not None:
            out[c] = out[c] / out.at[f, c] * raw.at[f, c]
            out.loc[out.index < f, c] = np.nan
    return out


def analyze(px, names, index_t, label):
    stocks = [c for c in px.columns if c != index_t]
    px = clean(px[px[index_t].notna()])
    start = px.index[260]  # モメンタム計算に1年分必要
    strategies = {
        "指数そのもの": ("index", 252),
        "全銘柄に均等投資": ("equal", 252),
        "① 12ヶ月モメンタム": ("mom", 252),
        "① 6ヶ月モメンタム": ("mom", 126),
        "② 12ヶ月＋相場フィルター": ("mom_filter", 252),
        "③ 12ヶ月＋押し目買い": ("mom_dip", 252),
    }
    curves = {}
    for name, (kind, lb) in strategies.items():
        c = run(px, stocks, index_t, kind, lb)
        curves[name] = c[c.index >= start] / c[c.index >= start].iloc[0]
        print(label, name, f"{stats(curves[name])[0]['年率リターン']*100:+.1f}%")
    i = len(px) - 1
    top = momentum_rank(px[stocks], i, 252)
    picks = [(t, px[t].iloc[i - SKIP] / px[t].iloc[i - 252] - 1, px[t].iloc[i]) for t in top]
    return section(f"{label}（{len(stocks)}銘柄）", curves, picks, names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=12)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--exclude-semis", action="store_true", help="半導体関連を除いた版も計算する")
    ap.add_argument("--exclude-ai", action="store_true", help="AI関連を除いた版も計算する")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    sections = []
    if args.demo:
        px, names = demo_prices()
        sections.append(analyze(px, names, "INDEX", "ダミーデータ"))
    else:
        for label, loader, index_t in (("日本株 TOPIX500", load_japan, "1306.T"),
                                       ("米国株 S&P500", load_us, "SPY")):
            names = loader()
            print(label, len(names), "銘柄を取得中…")
            px = download(list(names) + [index_t], args.years)
            stocks = [c for c in px.columns if c != index_t]
            if args.exclude_ai:
                ai = find_ai(stocks)
                print(label, "AI関連として除外:", len(ai), "銘柄")
                print("  " + ", ".join(f"{names.get(t, t)}({t})" for t in sorted(ai)))
                sections.append(analyze(px.drop(columns=list(ai)), names, index_t,
                                        label + " AI関連除く"))
            if args.exclude_semis:
                semis = find_semis([c for c in px.columns if c != index_t])
                print(label, "半導体関連として除外:", len(semis), "銘柄")
                print("  " + ", ".join(f"{names.get(t, t)}({t})" for t in sorted(semis)))
                sections.append(analyze(px.drop(columns=list(semis)), names, index_t,
                                        label + " 半導体除く"))
            sections.append(analyze(px, names, index_t, label))

    os.makedirs(args.out, exist_ok=True)
    html = (f"<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>モメンタム検証</title><style>{CSS}</style></head><body>"
            "<h1>モメンタム戦略のバックテスト</h1><p class='note'>毎月末に上位10銘柄へ入れ替え。"
            "手数料・スリッページとして片道0.1%を差し引き。税金は考慮していません。"
            "グラフは対数目盛（1→2倍と2→4倍が同じ高さ）。<br>注意: 銘柄は<b>現在の</b>"
            "TOPIX500・S&P500構成銘柄から選んでいるため、過去に除外・上場廃止された銘柄が含まれず、"
            "全体的に結果が良く出ます。比較は「全銘柄に均等投資」と比べるのが公平です。</p>"
            + "".join(sections) + "</body></html>")
    with open(f"{args.out}/momentum_report.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("完了:", f"{args.out}/momentum_report.html")


if __name__ == "__main__":
    main()
