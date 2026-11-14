"""Pre-registered protocol for the Smart Zone Pro multi-timeframe study.

FROZEN before any outcome was computed (2026-11-08):

Data:   Binance USD-M BTCUSDT perp 1m (data/binance_ob_timeframes/minutes.parquet), 2023-11..2026-10, no gaps.
Splits: warmup 2023-11/12; TRAIN 2024; VALIDATION 2025; TEST (holdout) 2026-01-01..2026-10-31.
        run_dev.py hard-truncates data at 2025-12-31 so test bars are not loaded at all.
Grid:   8 HTF/LTF combos x 2 presets x 13 filters x 5 exits = 1040 variants.
Select: per combo, require train n>=40, val n>=20, mean net R>0 in both; pick highest min(train,val) mean R.
        Holdout tested only on finalists + 4 fixed baselines. Holm over those.
Costs:  base = 0.05% taker + 0.02% slippage per side + funding. Scenarios below.
Ties:   stop checked first in any minute; entry is the next 1m open after the trigger bar closes.
Indicator assumptions are those in EngineCfg; sensitivity is reported, not selected on.
"""
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MINUTES = ROOT / "data/binance_ob_timeframes/minutes.parquet"
FUNDING = ROOT / "data/binance_ob_timeframes/funding.parquet"
DELTA_1M = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
OUT = Path(__file__).resolve().parent / "results"

TRAIN = ("2024-01-01", "2025-01-01")
VAL = ("2025-01-01", "2026-01-01")
TEST = ("2026-01-01", "2026-11-01")
DEV_END = "2026-01-01"

TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1D": 1440}
COMBOS = [("1h", "5m"), ("1h", "15m"), ("4h", "5m"), ("4h", "15m"), ("4h", "1h"),
          ("1D", "5m"), ("1D", "15m"), ("1D", "1h")]
PRESETS = {"Balanced": dict(max_zones=5, min_strength=1.25, max_width=1.0),
           "Strict": dict(max_zones=3, min_strength=1.75, max_width=0.6)}
FILTERS = ["none", "ema200", "adx_le25", "adx_gt25", "ema200_adx_le25", "session_ldn_ny", "session_asia",
           "vol_low", "vol_high", "star2plus", "star3plus", "first_touch", "flip_only"]
EXITS = ["fixed_0.5R", "fixed_1R", "fixed_2R", "next_zone", "atr_trail"]
BASELINES = [("4h", "15m", "Balanced", "ema200_adx_le25", "fixed_0.5R"),
             ("4h", "15m", "Balanced", "ema200_adx_le25", "fixed_1R"),
             ("1h", "15m", "Balanced", "ema200_adx_le25", "fixed_0.5R"),
             ("4h", "1h", "Balanced", "none", "fixed_1R")]
SELECT_MIN_TRAIN, SELECT_MIN_VAL = 40, 20
# entry cost, exit cost (fraction of notional per side incl. slippage), funding on?
COSTS = {"base": (0.0007, 0.0007, True), "base_gst": (0.00079, 0.00079, True),
         "maker_entry": (0.0002, 0.0007, True), "zero": (0.0, 0.0, False)}
MAX_HOLD_MIN = 96 * 60
MIN_RISK_PCT = 0.002


@dataclass(frozen=True)
class EngineCfg:
    """Every field is an assumption where the indicator description is silent."""
    pivot_l: int = 5
    pivot_r: int = 5
    cluster_mult: float = 0.5   # join if |price-cluster mean| <= mult*min(pivot ATR, zone avg ATR)
    tau: float = 150.0          # recency decay constant, HTF bars
    lookback: int = 500         # HTF bars of pivots kept
    flip_gap: int = 5           # min bars between S/R phases
    flip_bonus: float = 0.5
    width_pen: float = 0.3      # W.Pen on user's chart
    floor_width: float = 0.1    # min zone width in ATR
    min_touches: int = 2
    break_invalidate: bool = False
    depth_min: float = 0.1      # fraction of width wick must enter
    depth_max: float = 1.0      # fraction of width wick may enter
    margin_atr: float = 0.1     # close beyond edge by margin*LTF ATR
    stop_buf: float = 0.25      # stop beyond far edge, zone ATRs


DEFAULT = EngineCfg()
SENS = {"pivot3": replace(DEFAULT, pivot_l=3, pivot_r=3), "pivot8": replace(DEFAULT, pivot_l=8, pivot_r=8),
        "cluster.25": replace(DEFAULT, cluster_mult=.25), "cluster.75": replace(DEFAULT, cluster_mult=.75),
        "tau75": replace(DEFAULT, tau=75.), "tau300": replace(DEFAULT, tau=300.),
        "lookback300": replace(DEFAULT, lookback=300), "lookback800": replace(DEFAULT, lookback=800),
        "flipgap1": replace(DEFAULT, flip_gap=1), "flipgap15": replace(DEFAULT, flip_gap=15),
        "floor.05": replace(DEFAULT, floor_width=.05), "floor.2": replace(DEFAULT, floor_width=.2),
        "touch1": replace(DEFAULT, min_touches=1), "break_inval": replace(DEFAULT, break_invalidate=True),
        "depth.05": replace(DEFAULT, depth_min=.05), "depth.25": replace(DEFAULT, depth_min=.25),
        "depthmax1.5": replace(DEFAULT, depth_max=1.5), "margin0": replace(DEFAULT, margin_atr=0.),
        "margin.25": replace(DEFAULT, margin_atr=.25), "stop.5": replace(DEFAULT, stop_buf=.5)}
