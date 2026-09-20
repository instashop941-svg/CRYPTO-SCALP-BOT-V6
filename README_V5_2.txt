SCALP V5.2 — STRUCTURAL SL

Based on V5.1. Core signal detection is unchanged:
SSL/BSL SWEEP -> POI -> REACTION -> DISPLACEMENT -> CHoCH/BOS -> IMB.

Unchanged:
- 5m context filter
- closed 1m candles only
- TP1 = 0.50%
- TP2 = 0.70%
- 30x default leverage
- anti-chase
- POI/IMB logic
- Telegram confirmed-entry output

V5.2 change:
- SL is beyond the deepest structural invalidation among sweep extreme, POI and IMB.
- Adds a dynamic buffer based on recent 1m true-range median (ATR-like) plus minimum structural clearance.
- Rejects any setup where SL is not strictly beyond the structural invalidation.
- Existing MAX_RISK_PCT = 2.50% remains the hard maximum.

Environment variables added:
SL_BUFFER_PCT=0.0015
SL_ATR_MULT=0.50
MIN_SL_CLEARANCE_PCT=0.0010

These are buffers around structural invalidation, not entry-based TP/SL percentages.

Do not merge this into main. Run as a separate V5.2 test service/branch so V5.1 remains unchanged.
