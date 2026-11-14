"""Backtest the signals from order_block_new.txt ("MYTradeSetup") on 15m BTCUSD.

The Pine file defines signals only (Hull/Kalman Buy/Sell crosses, pivot-gated reversal candles),
no exits, so every variant uses the same assumed exit: stop 1.5 x ATR(15m), trailing 1 x ATR
once 1R ahead, 96h cap. Each variant is run alone and gated by a live same-direction 15m order
block that the signal bar touches. The directional null test (no stop/trail) comes first because
it does not depend on any exit assumption. Entries are at the open after the signal bar closes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from strategy.mytradesetup import (
    hull_cross_signals, order_block_confluence, reversal_signals, signal_entries, simulate_signals,
)
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, aggregate, clean_minutes
from strategy.ob_touch_15m import TrailConfig, blocks_15m, directional_edge, monthly


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")
TRAIL = TrailConfig(stop_buffer_atr=0.0, trail_activate_r=1.0, trail_atr_mult=1.0, max_hours=96, min_stop_pct=0.002)


def stats(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0}
    wins, losses = trades.loc[trades["ret_net"] > 0, "ret_net"], trades.loc[trades["ret_net"] <= 0, "ret_net"]
    return {
        "trades": len(trades), "win_%": round((trades["ret_net"] > 0).mean() * 100, 1),
        "net_%": round(trades["ret_net"].sum() * 100, 1),
        "PF": round(wins.sum() / abs(losses.sum()), 2) if len(losses) else float("inf"),
        "total_R": round(trades["r_net"].sum(), 1),
    }


def main() -> None:
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    path = MinutePath(minutes)
    bars = aggregate(minutes, 15)
    _, blocks = blocks_15m(minutes, 15)
    confluence = order_block_confluence(bars, blocks)
    families = {
        "hull_kalman": hull_cross_signals(bars),
        "reversal_as_written": reversal_signals(bars, reversal_fixed=False),
        "reversal_fixed_short": reversal_signals(bars, reversal_fixed=True),
    }

    print(f"15m bars {len(bars)}, order blocks {len(blocks)}; costs {FEE_PER_SIDE:.4%}/side")
    rows, nulls = [], []
    for name, signals in families.items():
        for gate, mask in (("alone", None), ("+OB touch", confluence)):
            label = f"{name} {gate}"
            entries = signal_entries(bars, signals, path, mask=mask)
            if entries.empty:
                rows.append({"variant": label, "signals": 0})
                continue
            assert (entries["entry_time"] >= entries["signal_time"]).all(), "entry before signal bar closed"
            trades = simulate_signals(entries, path, TRAIL)
            train = trades[trades["entry_time"] < TEST_START]
            test = trades[trades["entry_time"] >= TEST_START]
            m = monthly(trades)
            full = stats(trades)
            rows.append({"variant": label, "signals": len(entries), **full,
                         "train_win_%": stats(train).get("win_%"), "test_win_%": stats(test).get("win_%"),
                         "train_net_%": stats(train).get("net_%"), "test_net_%": stats(test).get("net_%"),
                         "months>=60%": f"{int((m['win_%'] >= 60).sum())}/{len(m)}"})
            edge = directional_edge(entries, path)
            nulls.append((label, len(entries), edge.set_index("horizon_h")["hit_rate_%"].round(1).to_dict()))

    pd.set_option("display.width", 220)
    print("\n=== Simulated trades (stop 1.5 ATR, 1 ATR trail after 1R) ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n=== Directional null test: forward hit-rate % at 1h/4h/24h from the entry, no stop/trail ===")
    for label, n, hits in nulls:
        print(f"{label:38s} n={n:5d}  {hits}")


if __name__ == "__main__":
    main()
