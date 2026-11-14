"""Backtest the daily SMA50/EMA7/RSI2/ADX2 long-only rules against buy-and-hold."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from strategy.daily_sma_ema_rsi_adx import add_indicators


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
FEE_PER_SIDE = 0.00059


def daily_bars(minutes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate UTC one-minute OHLCV candles into daily candles."""
    return minutes.resample("1D", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "high", "low", "close"])


def split_data_blocks(bars: pd.DataFrame) -> list[pd.DataFrame]:
    """Split daily candles wherever a full calendar day or more is missing."""
    groups = bars.index.to_series().diff().gt(pd.Timedelta(days=1)).cumsum()
    return [block for _, block in bars.groupby(groups)]


def trade_record(
    signal_time: pd.Timestamp,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    entry: float,
    exit_price: float,
    entry_equity: float,
    exit_equity: float,
    reason: str,
) -> dict[str, object]:
    """Create one fully allocated long trade record."""
    return {
        "signal_time": signal_time,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry": entry,
        "exit": exit_price,
        "reason": reason,
        "ret_gross": exit_price / entry - 1,
        "ret_net": exit_equity / entry_equity - 1,
    }


def run_strategy_block(
    raw_block: pd.DataFrame,
    starting_equity: float,
) -> tuple[pd.DataFrame, pd.Series, float]:
    """Apply signals at close and fill entries/exits at the following open."""
    block = add_indicators(raw_block)
    equity = starting_equity
    in_position = False
    quantity = 0.0
    entry_price = 0.0
    entry_equity = 0.0
    signal_time = pd.Timestamp(0, tz="UTC")
    entry_time = pd.Timestamp(0, tz="UTC")
    trades: list[dict[str, object]] = []
    equity_points: list[float] = []

    for i, (timestamp, bar) in enumerate(block.iterrows()):
        if i > 0:
            previous = block.iloc[i - 1]
            if in_position and bool(previous["exit_signal"]):
                exit_price = float(bar["open"])
                equity = quantity * exit_price * (1 - FEE_PER_SIDE)
                trades.append(trade_record(
                    signal_time, entry_time, timestamp, entry_price, exit_price,
                    entry_equity, equity, "signal",
                ))
                in_position = False
                quantity = 0.0
            elif not in_position and bool(previous["entry_signal"]):
                entry_price = float(bar["open"])
                entry_equity = equity
                quantity = equity * (1 - FEE_PER_SIDE) / entry_price
                signal_time = block.index[i - 1]
                entry_time = timestamp
                in_position = True

        if in_position:
            equity = quantity * float(bar["close"])

        is_last = i == len(block) - 1
        if is_last and in_position:
            exit_price = float(bar["close"])
            equity = quantity * exit_price * (1 - FEE_PER_SIDE)
            trades.append(trade_record(
                signal_time, entry_time, timestamp, entry_price, exit_price,
                entry_equity, equity, "data_block_end",
            ))
            in_position = False
        equity_points.append(equity)

    return pd.DataFrame(trades), pd.Series(equity_points, index=block.index), equity


def run_buy_and_hold(
    blocks: list[pd.DataFrame],
) -> tuple[pd.Series, float]:
    """Buy at the first open and flatten at each available data block's last close."""
    equity = 1.0
    points: list[pd.Series] = []
    for block in blocks:
        if block.empty:
            continue
        quantity = equity * (1 - FEE_PER_SIDE) / float(block["open"].iloc[0])
        marked = block["close"] * quantity
        marked.iloc[-1] *= 1 - FEE_PER_SIDE
        points.append(marked)
        equity = float(marked.iloc[-1])
    curve = pd.concat(points).sort_index() if points else pd.Series(dtype=float)
    return curve, equity


def performance(curve: pd.Series, trades: pd.DataFrame, final_equity: float) -> dict[str, float | int]:
    """Summarize returns and marked-to-market drawdown."""
    start, end = curve.index.min(), curve.index.max()
    years = max((end - start).total_seconds() / (365.25 * 86400), 1 / 365.25)
    total_return = (final_equity - 1) * 100
    cagr = ((final_equity ** (1 / years)) - 1) * 100 if final_equity > 0 else -100.0
    drawdown = curve / curve.cummax() - 1
    winners = trades[trades["ret_net"] > 0] if not trades.empty else trades
    losers = trades[trades["ret_net"] < 0] if not trades.empty else trades
    profit_factor = (
        winners["ret_net"].sum() / abs(losers["ret_net"].sum())
        if not losers.empty else float("inf") if not winners.empty else 0.0
    )
    return {
        "total_return_%": total_return,
        "CAGR_%": cagr,
        "max_drawdown_%": float(drawdown.min() * 100),
        "trades": len(trades),
        "win_rate_%": float((trades["ret_net"] > 0).mean() * 100) if not trades.empty else 0.0,
        "profit_factor": float(profit_factor),
    }


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to create the one-minute Parquet file.")
    minutes = pd.read_parquet(MINUTE_DATA)
    daily = daily_bars(minutes)
    blocks = split_data_blocks(daily)
    daily_path = ROOT / "data/parquet/BTCUSD_1d_20260101_20261026.parquet"
    daily.to_parquet(daily_path, compression="zstd")

    trades_per_block: list[pd.DataFrame] = []
    curves: list[pd.Series] = []
    equity = 1.0
    for block in blocks:
        trades, curve, equity = run_strategy_block(block, equity)
        if not trades.empty:
            trades_per_block.append(trades)
        curves.append(curve)
    trades = pd.concat(trades_per_block, ignore_index=True) if trades_per_block else pd.DataFrame()
    strategy_curve = pd.concat(curves).sort_index()
    buy_hold_curve, buy_hold_equity = run_buy_and_hold(blocks)

    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trades_path = report_dir / "daily_sma_ema_rsi_adx_trades.csv"
    equity_path = report_dir / "daily_sma_ema_rsi_adx_equity.csv"
    trades.to_csv(trades_path, index=False)
    pd.DataFrame({
        "strategy_equity": strategy_curve,
        "buy_hold_equity": buy_hold_curve.reindex(strategy_curve.index).ffill().fillna(1.0),
    }).to_csv(equity_path, index_label="date")

    print("=== Daily SMA50 + EMA7 + RSI2/ADX2 backtest ===")
    print(f"Data range: {daily.index.min()} to {daily.index.max()} UTC ({len(daily):,} daily candles)")
    print("Coverage blocks:")
    for block in blocks:
        print(f"  {block.index.min().date()} to {block.index.max().date()} ({len(block)} days)")
    print("Execution: next daily open; full notional; flat at each data-block end")
    print(f"Fees: {FEE_PER_SIDE:.4%} per side; no slippage or funding")
    print("\nStrategy:")
    for key, value in performance(strategy_curve, trades, equity).items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    print("\nBuy and hold (restarted per available data block):")
    for key, value in performance(buy_hold_curve, pd.DataFrame(), buy_hold_equity).items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    if not trades.empty:
        print("\nTrades:")
        print(trades.to_string(index=False))
    print(f"\nDaily Parquet: {daily_path.relative_to(ROOT)}")
    print(f"Trade list:    {trades_path.relative_to(ROOT)}")
    print(f"Equity curves: {equity_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
