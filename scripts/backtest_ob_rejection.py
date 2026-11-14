"""Backtest the researched 1h/4h order-block rejection strategy with 15m entries.

Rules (chosen by scripts/research_ob_rejection.py, train Jan-May / test Jul-Oct 2026):
  zones   LuxAlgo internal order blocks on 1h and 4h, live until price trades through the far side
  entry   a closed 15m candle wicks into a live zone, stays inside its far side and closes back
          outside it; fill at the next 15m open
  filters trade with the 15m EMA200; only while 4h ADX(14) <= 25
  exits   stop 0.5 x ATR(15m) beyond the zone's far side, target 0.5R, 96h time stop; walked on
          1m candles, a minute touching both stop and target counts as a stop
  costs   0.059% per side, plus SLIPPAGE_PER_SIDE; one position at a time
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from strategy.ob_rejection import (
    FEE_PER_SIDE,
    MinutePath,
    StrategyConfig,
    clean_minutes,
    monthly,
    simulate,
    strategy_events,
)


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
SLIPPAGE_PER_SIDE = 0.0
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")


def equity_curve(trades: pd.DataFrame) -> pd.Series:
    """Compounded equity at each exit, trading full equity at 1x notional."""
    if trades.empty:
        return pd.Series(dtype=float)
    return (1 + trades.set_index("exit_time")["ret_net"]).cumprod()


def summary(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"trades": 0}
    wins = trades.loc[trades["ret_net"] > 0, "ret_net"]
    losses = trades.loc[trades["ret_net"] <= 0, "ret_net"]
    curve = equity_curve(trades)
    return {
        "trades": len(trades),
        "win_rate_%": (trades["ret_net"] > 0).mean() * 100,
        "return_%": (curve.iloc[-1] - 1) * 100,
        "max_drawdown_%": float((curve / curve.cummax().clip(lower=1) - 1).min() * 100),
        "profit_factor": wins.sum() / abs(losses.sum()) if len(losses) else float("inf"),
        "total_R": trades["r_net"].sum(),
        "avg_risk_%": trades["risk_%"].mean(),
    }


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to generate one-minute candles.")
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    config = StrategyConfig()
    events = strategy_events(minutes, config)
    trades = simulate(events, MinutePath(minutes), config.exit, FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
    months = monthly(trades)

    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(report_dir / "ob_rejection_trades.csv", index=False)
    months.to_csv(report_dir / "ob_rejection_monthly.csv", index_label="month")
    equity_curve(trades).rename("equity").to_csv(report_dir / "ob_rejection_equity.csv", index_label="time")

    print("=== 1h/4h order-block rejection -> 15m entries ===")
    print(f"Data: {minutes.index.min()} to {minutes.index.max()} UTC (June and most of September missing)")
    print(f"Signals after filters: {len(events)}; taken one at a time: {len(trades)}")
    print(f"Costs: {FEE_PER_SIDE + SLIPPAGE_PER_SIDE:.4%} per side; returns at 1x notional, R = net / stop distance")
    for label, part in (
        ("All", trades),
        ("Train Jan-May", trades[trades["entry_time"] < TEST_START]),
        ("Test Jul-Oct", trades[trades["entry_time"] >= TEST_START]),
    ):
        stats = summary(part)
        print(f"\n{label}: " + ", ".join(
            f"{key} {value:.2f}" if isinstance(value, float) else f"{key} {value}" for key, value in stats.items()
        ))
    print("\nMonthly:")
    print(months.round(2).to_string())
    hit = int((months["win_%"] >= 60).sum())
    print(f"\nMonths with win rate >= 60%: {hit}/{len(months)}; profitable months: {(months['net_%'] > 0).sum()}/{len(months)}")
    print("\nTrades:")
    columns = ["signal_time", "ob_tf", "side", "touch", "entry_time", "exit_time", "entry", "stop", "target",
               "exit", "exit_reason", "risk_%", "ret_net", "r_net"]
    print(trades[columns].to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nReports: data/reports/ob_rejection_trades.csv, ob_rejection_monthly.csv, ob_rejection_equity.csv")


if __name__ == "__main__":
    main()
