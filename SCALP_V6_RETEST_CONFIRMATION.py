"""
SCALP V6 — MEXC Futures Signal Bot
Separate V6 bot. Does NOT modify ETH V4 FIXED.

Workflow:
1H  -> direction + major zones
15m -> structure + liquidity
10m -> scenario confirmation
5m  -> entry trigger

Core setup:
WAIT -> LIQUIDITY SWEEP -> CHoCH/BOS -> IMB/FVG -> RETEST -> 5m CONFIRMATION -> ENTRY

Educational/trading automation template. Test on paper/demo before live use.
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict

import ccxt
import pandas as pd
import numpy as np
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | V6 | %(levelname)s | %(message)s"
)

SYMBOLS = os.getenv(
    "SYMBOLS",
    "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT,"
    "HBAR/USDT:USDT,JUP/USDT:USDT,LINK/USDT:USDT,VIRTUAL/USDT:USDT"
).split(",")

TIMEFRAMES = ["1h", "15m", "10m", "5m"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
LEVERAGE = int(os.getenv("LEVERAGE", "30"))
RR = float(os.getenv("RR", "2.0"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "7"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})


@dataclass
class Setup:
    symbol: str
    side: str
    score: int
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    reason: str


def telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.info("Telegram disabled:\n%s", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:
        logging.warning("Telegram error: %s", e)


def fetch(symbol: str, tf: str, limit: int = 160) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df = pd.DataFrame(
        raw, columns=["ts", "open", "high", "low", "close", "volume"]
    )
    return df


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df.high, df.low, df.close
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def ema(df: pd.DataFrame, n: int) -> pd.Series:
    return df.close.ewm(span=n, adjust=False).mean()


def swing_high(df: pd.DataFrame, n: int = 3) -> float:
    x = df.high.iloc[:-2]
    return float(x.tail(n * 4).max())


def swing_low(df: pd.DataFrame, n: int = 3) -> float:
    x = df.low.iloc[:-2]
    return float(x.tail(n * 4).min())


def detect_bias(df1h: pd.DataFrame) -> str:
    e20 = ema(df1h, 20).iloc[-2]
    e50 = ema(df1h, 50).iloc[-2]
    close = df1h.close.iloc[-2]
    if close > e20 > e50:
        return "LONG"
    if close < e20 < e50:
        return "SHORT"
    return "NEUTRAL"


def detect_structure(df15: pd.DataFrame) -> str:
    c = df15.iloc[-2]
    prev = df15.iloc[-8:-2]
    hi = prev.high.max()
    lo = prev.low.min()

    if c.close > hi:
        return "BULL_BOS"
    if c.close < lo:
        return "BEAR_BOS"

    # CHoCH proxy: last candle breaks the opposite side after a short pullback.
    if c.close > prev.high.tail(3).max():
        return "BULL_CHOCH"
    if c.close < prev.low.tail(3).min():
        return "BEAR_CHOCH"
    return "RANGE"


def liquidity_sweep(df: pd.DataFrame, side: str) -> bool:
    """Detect sweep of recent liquidity with close back inside the range."""
    x = df.iloc[:-2]
    last = df.iloc[-2]
    recent_hi = x.high.tail(12).max()
    recent_lo = x.low.tail(12).min()

    if side == "LONG":
        return last.low < recent_lo and last.close > recent_lo
    return last.high > recent_hi and last.close < recent_hi


def imbalance(df: pd.DataFrame, side: str) -> bool:
    """Simple 3-candle FVG/imbalance proxy."""
    a, b, c = df.iloc[-4], df.iloc[-3], df.iloc[-2]
    if side == "LONG":
        return c.low > a.high
    return c.high < a.low


def retest(df10: pd.DataFrame, side: str) -> bool:
    """Price returns to the latest 10m imbalance/impulse area."""
    a, b, c = df10.iloc[-5], df10.iloc[-4], df10.iloc[-3]
    if side == "LONG":
        if c.low <= a.high and c.close > c.open:
            return True
    else:
        if c.high >= a.low and c.close < c.open:
            return True
    return False


def trigger_5m(df5: pd.DataFrame, side: str) -> bool:
    """Entry trigger: rejection + direction candle."""
    x = df5.iloc[-3:-1]
    last = x.iloc[-1]
    prev = x.iloc[-2]

    if side == "LONG":
        return (
            last.close > last.open
            and last.close > prev.high
            and last.low <= prev.low
        )
    return (
        last.close < last.open
        and last.close < prev.low
        and last.high >= prev.high
    )


def build_setup(symbol: str) -> Optional[Setup]:
    try:
        d1h = fetch(symbol, "1h")
        d15 = fetch(symbol, "15m")
        d10 = fetch(symbol, "10m")
        d5 = fetch(symbol, "5m")

        bias = detect_bias(d1h)
        structure = detect_structure(d15)

        candidates = []
        if bias == "LONG" and structure in ("BULL_BOS", "BULL_CHOCH"):
            candidates.append("LONG")
        if bias == "SHORT" and structure in ("BEAR_BOS", "BEAR_CHOCH"):
            candidates.append("SHORT")

        if not candidates:
            return None

        side = candidates[0]
        score = 2
        reasons = [f"1H={bias}", f"15m={structure}"]

        if liquidity_sweep(d15, side):
            score += 2
            reasons.append("15m liquidity sweep")
        else:
            return None

        if imbalance(d10, side):
            score += 2
            reasons.append("10m imbalance/FVG")
        else:
            return None

        if retest(d10, side):
            score += 2
            reasons.append("10m retest")
        else:
            return None

        if trigger_5m(d5, side):
            score += 2
            reasons.append("5m confirmation")
        else:
            return None

        if score < MIN_SCORE:
            return None

        price = float(d5.close.iloc[-2])
        a = float(atr(d5).iloc[-2])
        if not np.isfinite(a) or a <= 0:
            return None

        # SL beyond recent 5m liquidity/sweep with ATR buffer.
        if side == "LONG":
            sweep_low = float(d5.low.tail(12).min())
            sl = sweep_low - 0.25 * a
            risk = price - sl
            if risk <= 0:
                return None
            tp1 = price + risk * 1.0
            tp2 = price + risk * RR
            entry_low = price - 0.20 * a
            entry_high = price + 0.05 * a
        else:
            sweep_high = float(d5.high.tail(12).max())
            sl = sweep_high + 0.25 * a
            risk = sl - price
            if risk <= 0:
                return None
            tp1 = price - risk * 1.0
            tp2 = price - risk * RR
            entry_low = price - 0.05 * a
            entry_high = price + 0.20 * a

        return Setup(
            symbol=symbol,
            side=side,
            score=score,
            entry_low=min(entry_low, entry_high),
            entry_high=max(entry_low, entry_high),
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            reason=" | ".join(reasons),
        )

    except Exception as e:
        logging.warning("%s: %s", symbol, e)
        return None


def format_signal(s: Setup) -> str:
    emoji = "🟢 LONG" if s.side == "LONG" else "🔴 SHORT"
    return (
        f"{emoji}\n"
        f"V6 SCALP — {s.symbol}\n\n"
        f"Score: {s.score}/10\n"
        f"Entry: {s.entry_low:.8g} – {s.entry_high:.8g}\n"
        f"SL: {s.sl:.8g}\n"
        f"TP1: {s.tp1:.8g}\n"
        f"TP2: {s.tp2:.8g}\n"
        f"Leverage: {LEVERAGE}x\n\n"
        f"CONFIRMATION:\n{s.reason}\n\n"
        f"⚠️ Це сигнал алгоритму, не гарантія результату."
    )


def main():
    logging.info("SCALP V6 started | symbols=%s", ",".join(SYMBOLS))
    last_sent: Dict[str, float] = {}

    while True:
        for symbol in SYMBOLS:
            symbol = symbol.strip()
            if not symbol:
                continue

            setup = build_setup(symbol)
            if setup is None:
                continue

            # Avoid duplicate alerts for the same symbol for 30 minutes.
            now = time.time()
            if now - last_sent.get(symbol, 0) < 1800:
                continue

            msg = format_signal(setup)
            telegram(msg)
            logging.info(msg)
            last_sent[symbol] = now

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
