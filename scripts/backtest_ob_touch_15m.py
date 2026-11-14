"""Backtest the pure 15m order-block touch/near-touch strategy with an ATR trailing stop.

Rules (config/ob_touch_15m.yaml; research found no edge -- see that file's STATUS note):
  zones   LuxAlgo internal order blocks built directly on 15m candles
  entry   the first live-block touch, or near-touch within 0.25% of its near edge; resolved
          to the exact minute and fill price on 1m candles (live-fill style)
  stop    0.25 x ATR(15m) beyond the block's far side
  exit    once 1R ahead, the stop trails 1x ATR(15m) behind the best price seen; else a
          96h time stop; walked minute by minute
  costs   0.059% per side; one position at a time
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from strategy.luxalgo_internal_ob import pine_internal_blocks
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, aggregate, clean_minutes
from strategy.ob_touch_15m import StrategyConfig, blocks_15m, directional_edge, monthly, simulate, strategy_events


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
CONFIG_PATH = ROOT / "config/ob_touch_15m.yaml"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")


def equity_curve(trades: pd.DataFrame) -> pd.Series:
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
    config = StrategyConfig.load(CONFIG_PATH)
    entries = strategy_events(minutes, config)
    trades = simulate(entries, MinutePath(minutes), config.trail, FEE_PER_SIDE)
    months = monthly(trades)

    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(report_dir / "ob_touch_15m_trades.csv", index=False)
    months.to_csv(report_dir / "ob_touch_15m_monthly.csv", index_label="month")
    equity_curve(trades).rename("equity").to_csv(report_dir / "ob_touch_15m_equity.csv", index_label="time")

    print("=== 15m order-block touch/near-touch -> ATR trailing stop ===")
    print(f"Data: {minutes.index.min()} to {minutes.index.max()} UTC (June and most of September missing)")
    bars = aggregate(minutes, config.entry.entry_minutes)
    blocks, _ = pine_internal_blocks(bars, config.entry.visible_last or 10**6)
    print(f"15m blocks confirmed: {len(blocks)}; touch/near candidates taken as entries: {len(entries)}; "
          f"traded one at a time: {len(trades)}")

    print("\n--- Validation: order-block detection sanity ---")
    bullish = sum(1 for b in blocks if b.bias == 1)
    bearish = sum(1 for b in blocks if b.bias == -1)
    print(f"Bullish blocks: {bullish}, bearish blocks: {bearish}")
    bad_zone = sum(1 for b in blocks if b.top <= b.bottom)
    print(f"Blocks with top<=bottom (should be 0): {bad_zone}")
    early = int((entries["entry_time"] < entries["block_created_at"]).sum()) if not entries.empty else 0
    print(f"Entries filled before their block existed (should be 0): {early}")
    if not trades.empty:
        wrong_side = ((trades["side"] == "long") & (trades["top"] <= trades["bottom"])).sum()
        stop_inside_zone = (
            ((trades["side"] == "long") & (trades["stop0"] >= trades["bottom"]))
            | ((trades["side"] == "short") & (trades["stop0"] <= trades["top"]))
        ).sum()
        trail_against = (
            ((trades["side"] == "long") & (trades["final_stop"] < trades["stop0"]))
            | ((trades["side"] == "short") & (trades["final_stop"] > trades["stop0"]))
        ).sum()
        print(f"Trades whose initial stop is NOT beyond the zone (should be 0): {stop_inside_zone}")
        print(f"Trades whose trailing stop moved against the position (should be 0): {trail_against}")
        print(f"Side mismatches long vs zone shape (should be 0): {wrong_side}")

    print(f"\nCosts: {FEE_PER_SIDE:.4%} per side; returns at 1x notional, R = net / stop distance")
    for label, part in (
        ("All", trades),
        ("Train Jan-May", trades[trades["entry_time"] < TEST_START] if not trades.empty else trades),
        ("Test Jul-Oct", trades[trades["entry_time"] >= TEST_START] if not trades.empty else trades),
    ):
        stats = summary(part)
        print(f"\n{label}: " + ", ".join(
            f"{key} {value:.2f}" if isinstance(value, float) else f"{key} {value}" for key, value in stats.items()
        ))

    print("\nMonthly:")
    print(months.round(2).to_string())
    if len(months):
        hit = int((months["win_%"] >= 60).sum())
        print(f"\nMonths with win rate >= 60%: {hit}/{len(months)}; profitable months: {(months['net_%'] > 0).sum()}/{len(months)}")

    print("\nDirectional-edge null test (forward return from fill, no stop/trail):")
    edge = directional_edge(entries, MinutePath(minutes))
    print(edge.round(2).to_string(index=False))

    if not trades.empty:
        print("\nSample trades (first 10):")
        columns = ["signal_time", "side", "touch_type", "distance_pct", "block_id", "top", "bottom",
                   "entry_time", "entry", "stop0", "final_stop", "exit_time", "exit", "exit_reason",
                   "risk_%", "ret_net", "r_net"]
        print(trades[columns].head(10).to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    print("\nReports: data/reports/ob_touch_15m_trades.csv, ob_touch_15m_monthly.csv, ob_touch_15m_equity.csv")


if __name__ == "__main__":
    main()
