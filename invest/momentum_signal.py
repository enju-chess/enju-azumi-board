"""
米国株 6ヶ月モメンタムの銘柄選び（AI関連を除く S&P500）

ルール:
  毎月末の終値で「7ヶ月前→1ヶ月前」の上昇率を計算し、上位10銘柄を均等な金額で持つ。
  翌月末に入れ替える。AI関連（半導体製造関連・AIデータセンター関連）は対象外。

出力: invest/signal.json（スマホ用ページ invest/index.html が読み込む）
"""

import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import momentum_backtest as mb  # noqa: E402

LOOKBACK, SKIP, TOP_N = 126, 21, 10
OUT = os.path.join(os.path.dirname(__file__), "signal.json")


def ranking(px, i):
    m = (px.iloc[i - SKIP] / px.iloc[i - LOOKBACK] - 1).dropna()
    return m.sort_values(ascending=False)


def rows(rank, px_raw, i, names, n):
    out = []
    for t, m in rank.head(n).items():
        out.append(dict(ticker=t, name=names.get(t, t), sector=mb.SECTOR.get(t, ""),
                        momentum=round(float(m), 4),
                        price=round(float(px_raw[t].iloc[: i + 1].dropna().iloc[-1]), 2)))
    return out


def main():
    import yfinance as yf
    names = mb.load_us()
    tickers = list(names)
    raw = mb.download(tickers, 2)
    ai = mb.find_ai(list(raw.columns))
    raw = raw.drop(columns=[c for c in ai if c in raw.columns])
    px = mb.clean(raw)
    px = px[px.notna().sum(axis=1) > len(px.columns) * 0.8]  # 祝日などで欠けた日を除く

    last = len(px) - 1
    ends = sorted(mb.month_ends(px.index))
    # 月末の確定ランキング: 最新データの月がもう終わっていれば最新日、まだ途中なら前月末
    cur = px.index[-1]
    today_ny = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).date()
    if (today_ny.year, today_ny.month) != (cur.year, cur.month):
        month_end = cur
    else:
        month_end = max(d for d in ends if d < cur.replace(day=1))
    me_i = px.index.get_loc(month_end)

    fx = yf.download("JPY=X", period="5d", progress=False)["Close"].dropna()
    usdjpy = float(np.ravel(fx.values)[-1])

    official = ranking(px, me_i)
    latest = ranking(px, last)
    data = dict(
        updated=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        price_date=str(px.index[-1].date()),
        rule="S&P500（AI関連を除く）の6ヶ月モメンタム上位10銘柄を均等に持つ。毎月末に入れ替え。",
        usdjpy=round(usdjpy, 2),
        official=dict(date=str(month_end.date()), top=rows(official, raw, me_i, names, 15)),
        latest=dict(date=str(px.index[-1].date()), top=rows(latest, raw, last, names, 15)),
        excluded=sorted(f"{names.get(t, t)} ({t})" for t in ai),
        universe=len(px.columns),
    )
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: data[k] for k in ("updated", "price_date", "usdjpy")}, ensure_ascii=False))
    print("確定:", data["official"]["date"], [r["ticker"] for r in data["official"]["top"][:TOP_N]])
    print("最新:", data["latest"]["date"], [r["ticker"] for r in data["latest"]["top"][:TOP_N]])


if __name__ == "__main__":
    main()
