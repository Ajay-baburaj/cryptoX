"""Replay the order-block mitigation paper strategy (1h / 15m / 5m blocks) on historical Binance BTCUSDT 1m data.

Uses the exact same ``OB1hStrategy`` state machine as live paper trading.
Data: data/binance_ob_timeframes/minutes.parquet (Binance USD-M BTCUSDT perpetual, 2023-11..2026-10).
Periods follow research/ob_timeframe_protocol.md: development 2024, validation 2025, test Jan-Oct 2026.
Trail settings are chosen on development + validation only; the test period is reported, never used to choose.

    python scripts/backtest_ob_mitigation_1h.py            # configured strategy
    python scripts/backtest_ob_mitigation_1h.py --grid     # trail variants
    python scripts/backtest_ob_mitigation_1h.py --tf 15 --grid   # 15m blocks (config/ob_mitigation_15m.yaml)
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from itertools import product
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research.ob_timeframes import complete_bars  # noqa: E402
from strategy.ob_mitigation_1h import Config, OB1hStrategy, load_config, make_bars  # noqa: E402

DATA = ROOT / "data/binance_ob_timeframes/minutes.parquet"
OUT = ROOT / "data/reports"
PERIODS = {"development": ("2024-01-01", "2025-01-01"), "validation": ("2025-01-01", "2026-01-01"),
           "test": ("2026-01-01", "2026-11-01")}


def run(minutes: pd.DataFrame, bars: pd.DataFrame, cfg: Config, start: str, end: str) -> OB1hStrategy:
    s = OB1hStrategy(cfg)
    s.load_bars(bars)
    window = minutes.loc[start:end]
    window = window[window.index < pd.Timestamp(end, tz="UTC")]
    ns = window.index.as_unit("ns").asi8
    s.baseline(int(ns[0]))
    s.trail_cursor_ns = int(ns[0]) - 1
    for t, o, h, l, c in zip(ns, window.open.to_numpy(), window.high.to_numpy(), window.low.to_numpy(), window.close.to_numpy()):
        s.on_minute(int(t), o, h, l, c)
    return s


def summarize(s: OB1hStrategy) -> dict:
    st = s.stats()
    return {"n": st["trades"], "win_pct": round(st["win_rate"], 1), "mean_R": round(st["avg_r"], 3),
            "PF": None if st["profit_factor"] is None else round(st["profit_factor"], 2),
            "return_pct": round((s.balance / s.cfg.start_balance - 1) * 100, 1),
            "max_dd_pct": round(st["max_drawdown_pct"], 1), "avg_hold_h": round(st["avg_hold_hours"], 1),
            "fees_usd": round(st["fees"], 0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--tf", type=int, default=60, choices=(5, 15, 60), help="block timeframe in minutes")
    ap.add_argument("--periods", default=",".join(PERIODS), help="comma-separated subset of periods")
    args = ap.parse_args()
    label = {60: "1h", 15: "15m", 5: "5m"}[args.tf]
    cfg = load_config(ROOT / f"config/ob_mitigation_{label}.yaml")
    assert cfg.timeframe_minutes == args.tf, "config timeframe_minutes does not match --tf"
    minutes = pd.read_parquet(DATA)
    bars = make_bars(complete_bars(minutes, args.tf)[["open", "high", "low", "close", "volume"]], args.tf)
    prefix = "ob1h" if args.tf == 60 else f"ob{label}"
    periods = {k: PERIODS[k] for k in args.periods.split(",")}
    variants = [("configured", cfg)]
    if args.grid:
        variants = [(f"activate{a}_lookback{n}", replace(cfg, trail_activate_r=a, trail_lookback=n))
                    for a, n in product((0.0, 0.5, 1.0, 1.5, 2.0, 3.0), (1, 2, 3, 5))]
    rows = []
    clock = time.monotonic()
    for name, c in variants:
        for period, (start, end) in periods.items():
            s = run(minutes, bars, c, start, end)
            rows.append({"variant": name, "period": period, **summarize(s)})
            if not args.grid and period == "test":
                pd.DataFrame(s.trades).drop(columns=["stop_moves"]).to_csv(OUT / f"{prefix}_test_trades.csv", index=False)
            print(f"{name:22s} {period:11s} {rows[-1]}  [{time.monotonic() - clock:.0f}s]", flush=True)
    table = pd.DataFrame(rows)
    table.to_csv(OUT / (f"{prefix}_grid.csv" if args.grid else f"{prefix}_backtest.csv"), index=False)
    print(table.pivot(index="variant", columns="period", values="mean_R").to_string())


if __name__ == "__main__":
    main()
