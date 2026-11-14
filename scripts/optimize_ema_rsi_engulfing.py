"""Coarse parameter search with a chronological holdout for the EMA/RSI/engulfing strategy."""
from __future__ import annotations

from itertools import product
from pathlib import Path

import pandas as pd

from strategy.ema_rsi_engulfing import Params, compute, simulate, summary


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
HOLDOUT_START = pd.Timestamp("2026-08-01", tz="UTC")
FEE_PER_SIDE = 0.00059


def run_segments(bars: pd.DataFrame, params: Params) -> pd.DataFrame:
    """Run the simulator on continuous data segments, resetting across outages."""
    boundaries = bars.index.to_series().diff().gt(pd.Timedelta(minutes=5)).cumsum()
    trades: list[pd.DataFrame] = []
    for _, segment in bars.groupby(boundaries):
        if len(segment) <= params.ema_len + 1:
            continue
        signals = compute(segment, params, include_divergence=False)
        result = simulate(signals, fee_per_side=FEE_PER_SIDE)
        if not result.empty:
            trades.append(result)
    return pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()


def metrics(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"total_net_%": 0.0, "win_rate": 0.0, "max_dd_%": 0.0, "trades": 0}
    result = summary(trades)
    return {
        "total_net_%": float(result["total_net_%"]),
        "win_rate": float(result["win_rate"]),
        "max_dd_%": float(result["max_dd_%"]),
        "trades": int(result["trades"]),
    }


def main() -> None:
    if not DATA.exists():
        raise FileNotFoundError(f"Run `make strategy-backtest` first; missing {DATA}")
    bars = pd.read_parquet(DATA)
    train = bars[bars.index < HOLDOUT_START]
    holdout = bars[bars.index >= HOLDOUT_START]
    grid = product(
        (100, 200, 300),       # EMA length
        (45.0, 50.0, 55.0),   # RSI threshold
        (1.5, 2.0, 2.5),      # stop distance multiplier
        (1.5, 2.0, 2.5),      # target in R
        (False, True),        # long-only or mirrored shorts
    )

    rows: list[dict[str, object]] = []
    total = 3 * 3 * 3 * 3 * 2
    for number, (ema_len, rsi_mid, stop_mult, rr, allow_shorts) in enumerate(grid, start=1):
        params = Params(
            ema_len=ema_len,
            rsi_mid=rsi_mid,
            stop_mult=stop_mult,
            rr=rr,
            allow_shorts=allow_shorts,
        )
        train_trades = run_segments(train, params)
        train_result = metrics(train_trades)
        rows.append({
            "ema_len": ema_len,
            "rsi_mid": rsi_mid,
            "stop_mult": stop_mult,
            "rr": rr,
            "allow_shorts": allow_shorts,
            **{f"train_{key}": value for key, value in train_result.items()},
        })
        if number % 20 == 0:
            print(f"Scored {number}/{total} parameter sets", flush=True)

    results = pd.DataFrame(rows).sort_values(
        ["train_total_net_%", "train_max_dd_%"], ascending=[False, False]
    )
    # Inspect only the strongest in-sample candidates on the reserved period.
    candidates = results.head(10).copy()
    holdout_rows: list[dict[str, object]] = []
    for row in candidates.to_dict("records"):
        params = Params(
            ema_len=int(row["ema_len"]),
            rsi_mid=float(row["rsi_mid"]),
            stop_mult=float(row["stop_mult"]),
            rr=float(row["rr"]),
            allow_shorts=bool(row["allow_shorts"]),
        )
        out = metrics(run_segments(holdout, params))
        holdout_rows.append({f"holdout_{key}": value for key, value in out.items()})
    candidates = pd.concat(
        [candidates.reset_index(drop=True), pd.DataFrame(holdout_rows)], axis=1
    )

    out_path = ROOT / "data/reports/ema_rsi_parameter_search.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)
    candidates.to_csv(ROOT / "data/reports/ema_rsi_top_candidates.csv", index=False)

    baseline = results[
        (results.ema_len == 200) & (results.rsi_mid == 50.0)
        & (results.stop_mult == 2.0) & (results.rr == 2.0)
        & (results.allow_shorts == False)
    ].iloc[0]
    print("\n=== Chronological strategy tuning ===")
    print(f"Training: {train.index.min()} to {train.index.max()} ({len(train):,} bars)")
    print(f"Holdout:  {holdout.index.min()} to {holdout.index.max()} ({len(holdout):,} bars)")
    print(f"Fee:      {FEE_PER_SIDE:.4%} per side; no slippage/funding")
    print("\nBaseline parameters on training:")
    print(baseline.to_string())
    print("\nTop 10 by training return, with untouched holdout results:")
    columns = [
        "ema_len", "rsi_mid", "stop_mult", "rr", "allow_shorts",
        "train_trades", "train_total_net_%", "train_win_rate", "train_max_dd_%",
        "holdout_trades", "holdout_total_net_%", "holdout_win_rate", "holdout_max_dd_%",
    ]
    print(candidates[columns].to_string(index=False))
    print(f"\nFull search: {out_path.relative_to(ROOT)}")
    print(f"Top candidates: data/reports/ema_rsi_top_candidates.csv")


if __name__ == "__main__":
    main()
