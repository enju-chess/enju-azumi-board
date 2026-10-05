"""指定した銘柄の最新終値とドル円を表示する"""
import sys
import yfinance as yf
tickers = sys.argv[1].split(",") + ["JPY=X"]
d = yf.download(tickers, period="5d", auto_adjust=False, progress=False)["Close"].ffill().iloc[-1]
for t in tickers:
    print(f"{t},{d[t]:.2f}")
