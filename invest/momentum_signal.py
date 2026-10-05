"""
モメンタム10銘柄の銘柄選び（AI関連を除く）

  米国株: S&P500 の6ヶ月モメンタム（7ヶ月前→1ヶ月前の上昇率）上位10銘柄
  日本株: TOPIX500 の12ヶ月モメンタム（13ヶ月前→1ヶ月前の上昇率）上位10銘柄
          ＋押し目買い（終値が5日線を下回った翌日に買う）

毎月末の終値で確定し、翌月末に入れ替える。AI関連（半導体製造関連・AIデータセンター関連）は対象外。

  python momentum_signal.py us   → invest/signal.json
  python momentum_signal.py jp   → invest/signal_jp.json
"""

import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import momentum_backtest as mb  # noqa: E402

SKIP, TOP_N = 21, 10
HERE = os.path.dirname(__file__)
MARKETS = {
    "us": dict(load=lambda: mb.load_us(), lookback=126, utc_offset=-5, fx=True, dip=False,
               out="signal.json",
               rule="S&P500（AI関連を除く）の6ヶ月モメンタム上位10銘柄を均等な金額で持つ。毎月末に入れ替え。"),
    "jp": dict(load=lambda: mb.load_japan(), lookback=252, utc_offset=9, fx=False, dip=True,
               out="signal_jp.json",
               rule="TOPIX500（AI関連を除く）の12ヶ月モメンタム上位10銘柄を均等な金額で持つ。"
                    "新しく入った銘柄は、終値が5日線を下回った翌日に買う（押し目買い）。毎月末に入れ替え。"),
}


def ranking(px, i, lookback):
    m = (px.iloc[i - SKIP] / px.iloc[i - lookback] - 1).dropna()
    return m.sort_values(ascending=False)


def rows(rank, raw, i, names, n, dip):
    out = []
    for t, m in rank.head(n).items():
        s = raw[t].iloc[: i + 1].dropna()
        r = dict(ticker=t, name=names.get(t, t), sector=mb.SECTOR.get(t, ""),
                 momentum=round(float(m), 4), price=round(float(s.iloc[-1]), 2))
        if dip:
            ma5 = s.tail(5).mean()
            r["ma5"] = round(float(ma5), 2)
            r["dip"] = bool(s.iloc[-1] < ma5)
        out.append(r)
    return out


def main(market):
    import yfinance as yf
    cfg = MARKETS[market]
    names = cfg["load"]()
    raw = mb.download(list(names), 2)
    ai = mb.find_ai(list(raw.columns))
    raw = raw.drop(columns=[c for c in ai if c in raw.columns])
    px = mb.clean(raw)
    px = px[px.notna().sum(axis=1) > len(px.columns) * 0.8]  # 祝日などで欠けた日を除く

    last = len(px) - 1
    ends = sorted(mb.month_ends(px.index))
    # 月末の確定ランキング: 最新データの月がもう終わっていれば最新日、まだ途中なら前月末
    cur = px.index[-1]
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=cfg["utc_offset"])).date()
    if (today.year, today.month) != (cur.year, cur.month):
        month_end = cur
    else:
        month_end = max(d for d in ends if d < cur.replace(day=1))
    me_i = px.index.get_loc(month_end)

    usdjpy = 1.0
    if cfg["fx"]:
        fx = yf.download("JPY=X", period="5d", progress=False)["Close"].dropna()
        usdjpy = float(np.ravel(fx.values)[-1])

    lb = cfg["lookback"]
    data = dict(
        market=market,
        updated=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        price_date=str(px.index[-1].date()),
        rule=cfg["rule"],
        usdjpy=round(usdjpy, 2),
        dip_rule=cfg["dip"],
        official=dict(date=str(month_end.date()),
                      top=rows(ranking(px, me_i, lb), raw, last, names, 15, cfg["dip"])),
        latest=dict(date=str(px.index[-1].date()),
                    top=rows(ranking(px, last, lb), raw, last, names, 15, cfg["dip"])),
        excluded=sorted(f"{names.get(t, t)} ({t})" for t in ai),
        universe=len(px.columns),
    )
    with open(os.path.join(HERE, cfg["out"]), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: data[k] for k in ("market", "updated", "price_date", "usdjpy")}, ensure_ascii=False))
    print("確定:", data["official"]["date"], [r["ticker"] for r in data["official"]["top"][:TOP_N]])
    print("最新:", data["latest"]["date"], [r["ticker"] for r in data["latest"]["top"][:TOP_N]])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "us")
