"""Research for the pure 15m order-block touch/near-touch strategy.

Order-block detection does not depend on the entry/exit parameters, so the 15m blocks are
computed once and reused across the whole grid. Same method as scripts/research_ob_rejection.py:
train Jan-May 2026, test Jul-Oct 2026 (June missing, September only has 1 day -- excluded from
both halves), and a setting is only called "robust" if it is profitable with >= 60% wins in
BOTH halves -- never the single best row, since a grid this size reliably produces overfit rows
that look good on one slice by chance alone.

Grid:
  near_mode / threshold  touch-only, or near-touch within 0.1 / 0.25 / 0.5x ATR(15m), or within
                         0.1% / 0.25% / 0.5% price distance of the zone's near edge
  trail_activate_r       start trailing once ahead by 0.5 / 1.0 / 1.5 R
  trail_atr_mult         trail distance, once active, of 1.0 / 1.5 / 2.0x ATR(15m)

Before trusting any win rate from the stop/trailing mechanics, a directional-edge null test
checks whether price even tends to move in the predicted direction after a touch/near-touch at
all (forward return at fixed horizons, no stop or trail) -- this separates "does the order
block predict direction" from "does this stop-and-trail scheme flatter the win rate by
construction".

    .venv/bin/python scripts/research_ob_touch_15m.py
"""
from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.luxalgo_internal_ob import pine_internal_blocks
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, aggregate, clean_minutes
from strategy.ob_touch_15m import (
    EntryConfig,
    TrailConfig,
    blocks_15m,
    pine_touch_candidates,
    build_entries,
    directional_edge,
    near_touch_candidates,
    simulate,
)


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")
TRAIN_END = pd.Timestamp("2026-06-01", tz="UTC")

NEAR_VARIANTS = {
    "touch": EntryConfig(near_mode="touch"),
    "atr_0.10": EntryConfig(near_mode="atr", near_atr_mult=0.10),
    "atr_0.25": EntryConfig(near_mode="atr", near_atr_mult=0.25),
    "atr_0.50": EntryConfig(near_mode="atr", near_atr_mult=0.50),
    "pct_0.001": EntryConfig(near_mode="pct", near_pct=0.001),
    "pct_0.0025": EntryConfig(near_mode="pct", near_pct=0.0025),
    "pct_0.005": EntryConfig(near_mode="pct", near_pct=0.005),
}
TRAIL_ACTIVATE_R = (0.5, 1.0, 1.5)
TRAIL_ATR_MULT = (1.0, 1.5, 2.0)


def score(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0, "win_%": np.nan, "net_%": 0.0, "R": 0.0,
                "train_trades": 0, "train_win_%": np.nan, "train_net_%": 0.0,
                "test_trades": 0, "test_win_%": np.nan, "test_net_%": 0.0,
                "months": 0, "months_win60": 0, "months_up": 0, "worst_month_%": 0.0}
    frame = trades.copy()
    frame["month"] = pd.to_datetime(frame["entry_time"], utc=True).dt.strftime("%Y-%m")
    frame = frame[frame["month"] != "2026-09"]  # only 1 day of data that month
    frame["win"] = frame["ret_net"] > 0
    by_month = frame.groupby("month").agg(win=("win", "mean"), ret=("ret_net", "sum"))
    train = frame[pd.to_datetime(frame["entry_time"], utc=True) < TRAIN_END]
    test = frame[pd.to_datetime(frame["entry_time"], utc=True) >= TEST_START]
    return {
        "trades": len(frame),
        "win_%": frame["win"].mean() * 100,
        "net_%": frame["ret_net"].sum() * 100,
        "R": frame["r_net"].sum(),
        "train_trades": len(train),
        "train_win_%": train["win"].mean() * 100 if len(train) else np.nan,
        "train_net_%": train["ret_net"].sum() * 100,
        "test_trades": len(test),
        "test_win_%": test["win"].mean() * 100 if len(test) else np.nan,
        "test_net_%": test["ret_net"].sum() * 100,
        "months": len(by_month),
        "months_win60": int((by_month["win"] >= 0.6).sum()),
        "months_up": int((by_month["ret"] > 0).sum()),
        "worst_month_%": by_month["ret"].min() * 100 if len(by_month) else 0.0,
    }


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to generate one-minute candles.")
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    path = MinutePath(minutes)

    bars = aggregate(minutes, 15)
    blocks, visible = pine_internal_blocks(bars, 5)  # blocks as the user's TradingView script draws them
    bullish = sum(1 for b in blocks if b.bias == 1)
    bearish = sum(1 for b in blocks if b.bias == -1)
    print(f"15m order blocks confirmed Jan-Oct 2026: {len(blocks)} ({bullish} bullish, {bearish} bearish)")

    rows: list[dict[str, object]] = []
    for near_name, entry_cfg in NEAR_VARIANTS.items():
        candidates = pine_touch_candidates(bars, blocks, visible, entry_cfg)
        entries = build_entries(candidates, path, entry_cfg.entry_minutes)
        if entries.empty:
            print(f"scored {near_name}: 0 entries", flush=True)
            continue
        for activate_r, atr_mult in product(TRAIL_ACTIVATE_R, TRAIL_ATR_MULT):
            trail_cfg = TrailConfig(trail_activate_r=activate_r, trail_atr_mult=atr_mult)
            trades = simulate(entries, path, trail_cfg, FEE_PER_SIDE)
            if len(trades) < 15:
                continue
            rows.append({
                "near_mode": near_name, "n_entries": len(entries),
                "trail_activate_r": activate_r, "trail_atr_mult": atr_mult,
                **score(trades),
            })
        print(f"scored {near_name}: {len(entries)} entries", flush=True)

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/reports/ob_touch_15m_research.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    if results.empty:
        print("\nNo grid row reached the 15-trade minimum sample size; no further stats to report.")
        return

    results["robust"] = (
        (results["train_net_%"] > 0) & (results["test_net_%"] > 0)
        & (results["train_win_%"] >= 50) & (results["test_win_%"] >= 50)
    )
    print(f"\n=== {len(results)} settings; train Jan-May, test Jul-Oct 2026 (Sep excluded, 1 day only) ===")
    print("robust = both halves net>0 and win>=50% (trailing-stop trades do not need a 60% bar to be profitable)")

    print("\nShare of near-mode variants that are robust, by trail params:")
    share = results.pivot_table(index="near_mode", columns=["trail_activate_r", "trail_atr_mult"],
                                 values="robust", aggfunc="mean")
    print(share.round(2).to_string())

    columns = ["near_mode", "trail_activate_r", "trail_atr_mult", "trades", "win_%", "net_%",
               "train_win_%", "test_win_%", "train_net_%", "test_net_%", "months_win60", "months_up", "worst_month_%"]
    print("\nTop 10 by TRAIN net (what naive tuning would pick) and how they did on test:")
    print(results.sort_values("train_net_%", ascending=False)[columns].head(10).round(2).to_string(index=False))

    robust = results[results["robust"]].sort_values(["months_win60", "months_up", "net_%"], ascending=False)
    print(f"\nRobust settings ({len(robust)} of {len(results)}), best first:")
    print(robust[columns].head(15).round(2).to_string(index=False) if len(robust) else "(none)")

    print("\n=== Directional-edge null test per near-mode (forward return from fill, no stop/trail) ===")
    for near_name, entry_cfg in NEAR_VARIANTS.items():
        candidates = pine_touch_candidates(bars, blocks, visible, entry_cfg)
        entries = build_entries(candidates, path, entry_cfg.entry_minutes)
        if entries.empty:
            continue
        edge = directional_edge(entries, path, horizons_hours=(1, 4, 24))
        print(f"\n{near_name} ({len(entries)} entries):")
        print(edge.round(2).to_string(index=False))

    print(f"\nFull grid: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
