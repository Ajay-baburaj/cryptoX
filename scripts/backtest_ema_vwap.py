"""Backtest the EMA(9/20) + session VWAP intraday trend strategy from config/ema_vwap.yaml.

See that file's header for the research finding: as described, this strategy's signal has no
measurable directional edge on BTCUSD (forward hit rate 47-53% at every horizon tested, Jan-Oct
2026). This script runs the config anyway, so the result is visible rather than asserted, and
so this is ready to rerun if the user wants a different instrument, timeframe or data source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from strategy.ema_vwap import EmaVwapConfig, MinutePath, filter_mask, prepare_bars, signals, simulate
from strategy.ob_rejection import clean_minutes, monthly


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/ema_vwap.yaml"


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
    }


def main() -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    config = EmaVwapConfig.load(CONFIG_PATH)
    data_path = ROOT / raw["data"]["minute_parquet"]
    split = pd.Timestamp(raw["data"]["train_test_split"], tz="UTC")
    if not data_path.exists():
        raise FileNotFoundError(f"Run `make strategy-backtest` first; missing {data_path}")

    minutes = clean_minutes(pd.read_parquet(data_path))
    bars = prepare_bars(minutes, config)
    events = signals(bars, config)
    path = MinutePath(minutes)
    trades = simulate(events, path, config)
    months = monthly(trades)

    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(report_dir / "ema_vwap_trades.csv", index=False)
    months.to_csv(report_dir / "ema_vwap_monthly.csv", index_label="month")
    equity_curve(trades).rename("equity").to_csv(report_dir / "ema_vwap_equity.csv", index_label="time")

    print("=== EMA(9/20) + session VWAP intraday trend filter ===")
    print(f"Config: {CONFIG_PATH.relative_to(ROOT)}")
    print(f"Timeframe: {config.timeframe_minutes}m, trigger: {config.trigger}, stop: {config.stop} "
          f"({config.stop_atr}x ATR), target: {config.target_r}R, exit_on: {config.exit_on}")
    print(f"Filters: min_adx={config.min_adx}, htf={config.htf_filter}, skip_open={config.skip_open_minutes}min, "
          f"sides={config.sides}")
    print(f"Raw signals (before filters): {len(events)}; taken one at a time after filters: {len(trades)}")
    print(f"Costs: {config.fee_per_side:.4%} per side; returns at 1x notional, R = net / stop distance")

    for label, part in (
        ("All", trades),
        ("Train Jan-May", trades[trades["entry_time"] < split] if not trades.empty else trades),
        ("Test Jul-Oct", trades[trades["entry_time"] >= split] if not trades.empty else trades),
    ):
        stats = summary(part)
        print(f"\n{label}: " + ", ".join(
            f"{key} {value:.2f}" if isinstance(value, float) else f"{key} {value}" for key, value in stats.items()
        ))

    print("\nMonthly:")
    print(months.round(2).to_string() if not months.empty else "No trades.")
    if not months.empty:
        hit = int((months["win_%"] >= 60).sum())
        print(f"\nMonths with win rate >= 60%: {hit}/{len(months)}; profitable months: {(months['net_%'] > 0).sum()}/{len(months)}")

    print("\nSTATUS: research (2026-11-02) found no directional edge in this signal on BTCUSD — "
          "see config/ema_vwap.yaml header and data/reports/ema_vwap_research.csv. Not recommended for live trading.")
    print(f"\nReports: data/reports/ema_vwap_trades.csv, ema_vwap_monthly.csv, ema_vwap_equity.csv")


if __name__ == "__main__":
    main()
