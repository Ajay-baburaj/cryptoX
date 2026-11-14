"""Pre-registered protocol for the same-timeframe Smart Zone Pro study.

Frozen BEFORE any outcome was computed (2026-11-08). Do not edit after results exist.

Data: Binance USD-M BTCUSDT perp 1m + funding (data/binance_ob_timeframes), the
longest gap-free series in the repo, used as BTCUSD proxy. Delta BTCUSD 2026 1m is a
replication set only (frozen rules, no selection).

Holdout: warmup 2023-11..12 | dev 2024 | val 2025 | TEST 2026-01..10.
Stage 1 runs with minutes physically truncated at 2026-01-01 and writes selection.json;
stage 2 is run afterwards on the full data. Caveat: 2026 BTC was seen by OLDER studies
in this repo (different strategies), never by this one.

Selection (per timeframe, primary grid only, base costs): dev trades>=30, val trades>=20,
mean net R > 0 in BOTH, maximise min(dev mean, val mean). If none pass: no rule.

Fixed baseline (no selection): all zones, all stars, 1R target, 0.25 ATR stop buffer.
"""
DEV = ("2024-01-01", "2025-01-01")
VAL = ("2025-01-01", "2026-01-01")
TEST = ("2026-01-01", "2026-11-01")
SPLITS = {"dev": DEV, "val": VAL, "test": TEST}
TIMEFRAMES = [5, 15, 30, 60, 240]
PRESETS = ["Balanced", "Strict"]
ZONE_SETS = ["all", "sup", "res", "flip"]
STAR_SETS = ["all", 1, 2, 3, 4]
# (kind, value): R target multiple / opposite zone / time stop in source bars
EXITS = [("R", .5), ("R", 1.), ("R", 1.5), ("R", 2.), ("opp", None), ("time", 10), ("time", 30)]
STOP_BUFFERS = [0.1, 0.25, 0.5]
MAX_HOLD_BARS = 100
MIN_OPP_RR = 0.5
BASELINE = dict(zone="all", stars="all", exit="R1.0", buffer=0.25)
# name: (entry fee, entry slip, exit fee, exit slip, charge funding)
COSTS = {
    "zero":        (0, 0, 0, 0, False),
    "maker_entry": (.0002, 0, .0005, .0002, True),
    "taker_s1":    (.0005, .0001, .0005, .0001, True),
    "base":        (.0005, .0002, .0005, .0002, True),
    "base_gst":    (.00059, .0002, .00059, .0002, True),
    "repo_config": (.001, .0005, .001, .0005, True),
}
RISK_PCT = .005
MAX_LEVERAGE = 3.0
MIN_DEV, MIN_VAL = 30, 20
