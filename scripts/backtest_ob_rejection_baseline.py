"""Baseline (v1): 4h LuxAlgo internal OBs, 15m rejection entries, 2R-activated trail. Kept for comparison."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from strategy.luxalgo_internal_ob import OrderBlock, internal_order_blocks


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
FEE_PER_SIDE = 0.00059
OB_DISPLAY_COUNT = 5
TRAIL_MULTIPLE = 2.0
INITIAL_R_MULTIPLE = 2.0
TARGET_R = 2.0


def aggregate_bars(minutes: pd.DataFrame, timeframe: str, min_count: int) -> pd.DataFrame:
    """Aggregate UTC minute candles without fabricating candles in missing data."""
    grouped = minutes.resample(timeframe, closed="left", label="right", origin="start_day")
    bars = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        minute_count=("close", "count"),
    )
    expected = 240 if timeframe == "4h" else 15
    threshold = min_count if min_count else int(expected * 0.9)
    return bars.loc[bars["minute_count"] >= threshold].dropna(subset=["open", "high", "low", "close"])


def build_blocks(h4: pd.DataFrame) -> list[OrderBlock]:
    """Run internal-structure OB detection independently across data outages."""
    groups = h4.index.to_series().diff().gt(pd.Timedelta(hours=4)).cumsum()
    blocks: list[OrderBlock] = []
    for _, segment in h4.groupby(groups):
        blocks.extend(internal_order_blocks(segment))
    return blocks


def rejection_signal(
    timestamp: pd.Timestamp,
    bar: pd.Series,
    blocks: list[OrderBlock],
) -> dict[str, object] | None:
    """Return the newest visible-zone rejection confirmed by this closed 15m bar."""
    candle_start = timestamp - pd.Timedelta(minutes=15)
    visible = [
        block for block in blocks
        if block.created_at <= candle_start
        and block.expires_at is not None
        and candle_start < block.expires_at
    ]
    visible.sort(key=lambda block: (block.created_at, block.block_id), reverse=True)
    for block in visible[:OB_DISPLAY_COUNT]:
        candle_range = float(bar["high"] - bar["low"])
        if candle_range <= 0:
            continue
        if block.bias == 1 and bar["low"] <= block.top and bar["low"] >= block.bottom and bar["close"] > block.top:
            return {"side": 1, "block_id": block.block_id, "range": candle_range}
        if block.bias == -1 and bar["high"] >= block.bottom and bar["high"] <= block.top and bar["close"] < block.bottom:
            return {"side": -1, "block_id": block.block_id, "range": candle_range}
    return None


def simulate_segment(
    bars: pd.DataFrame,
    signals: dict[pd.Timestamp, dict[str, object]],
    starting_equity: float,
) -> tuple[pd.DataFrame, pd.Series, float]:
    """Fill next-open entries, apply 2x-candle stops, then trail after 2R."""
    equity = starting_equity
    position: dict[str, object] | None = None
    pending: dict[str, object] | None = None
    trades: list[dict[str, object]] = []
    curve: list[float] = []

    def mark_to_market(pos: dict[str, object], price: float) -> float:
        side = int(pos["side"])
        entry_equity = float(pos["entry_equity"])
        entry = float(pos["entry"])
        return entry_equity * (1 - FEE_PER_SIDE) * (1 + side * (price - entry) / entry)

    def close_trade(pos: dict[str, object], timestamp: pd.Timestamp, price: float, reason: str) -> float:
        nonlocal equity
        entry_equity = float(pos["entry_equity"])
        new_equity = mark_to_market(pos, price) * (1 - FEE_PER_SIDE)
        side = int(pos["side"])
        trades.append({
            "side": "long" if side == 1 else "short",
            "block_id": pos["block_id"],
            "signal_time": pos["signal_time"],
            "entry_time": pos["entry_time"],
            "exit_time": timestamp,
            "entry": float(pos["entry"]),
            "exit": price,
            "initial_stop": float(pos["initial_stop"]),
            "exit_reason": reason,
            "trail_activated": bool(pos["trail_active"]),
            "ret_gross": side * (price - float(pos["entry"])) / float(pos["entry"]),
            "ret_net": new_equity / entry_equity - 1,
        })
        equity = new_equity
        return new_equity

    for i, (timestamp, bar) in enumerate(bars.iterrows()):
        if position is None and pending is not None:
            side = int(pending["side"])
            entry = float(bar["open"])
            stop_distance = INITIAL_R_MULTIPLE * float(pending["range"])
            initial_stop = entry - side * stop_distance
            target = entry + side * TARGET_R * stop_distance
            position = {
                **pending,
                "entry": entry,
                "entry_time": timestamp,
                "entry_equity": equity,
                "initial_stop": initial_stop,
                "stop": initial_stop,
                "target": target,
                "trail_active": False,
                "favorable_extreme": entry,
            }
            pending = None

        if position is not None:
            side = int(position["side"])
            stop = float(position["stop"])
            open_price = float(bar["open"])
            stop_hit = open_price <= stop if side == 1 else open_price >= stop
            stop_fill = open_price
            if not stop_hit:
                stop_hit = float(bar["low"]) <= stop if side == 1 else float(bar["high"]) >= stop
                stop_fill = stop
            if stop_hit:
                reason = "trailing_stop" if bool(position["trail_active"]) else "initial_stop"
                close_trade(position, timestamp, stop_fill, reason)
                position = None
            else:
                target_hit = float(bar["high"]) >= float(position["target"]) if side == 1 else float(bar["low"]) <= float(position["target"])
                if target_hit:
                    position["trail_active"] = True
                if bool(position["trail_active"]):
                    candle_range = float(bar["high"] - bar["low"])
                    distance = TRAIL_MULTIPLE * candle_range
                    if side == 1:
                        position["favorable_extreme"] = max(float(position["favorable_extreme"]), float(bar["high"]))
                        new_stop = max(float(position["stop"]), float(position["favorable_extreme"]) - distance)
                        position["stop"] = new_stop
                        if float(bar["close"]) <= new_stop:
                            close_trade(position, timestamp, float(bar["close"]), "trailing_stop_close")
                            position = None
                    else:
                        position["favorable_extreme"] = min(float(position["favorable_extreme"]), float(bar["low"]))
                        new_stop = min(float(position["stop"]), float(position["favorable_extreme"]) + distance)
                        position["stop"] = new_stop
                        if float(bar["close"]) >= new_stop:
                            close_trade(position, timestamp, float(bar["close"]), "trailing_stop_close")
                            position = None
                if position is not None:
                    equity = mark_to_market(position, float(bar["close"]))

        if position is None and pending is None and timestamp in signals:
            pending = {**signals[timestamp], "signal_time": timestamp}
        curve.append(equity)

    if position is not None:
        final_time = bars.index[-1]
        close_trade(position, final_time, float(bars["close"].iloc[-1]), "data_gap")
        curve[-1] = equity
    return pd.DataFrame(trades), pd.Series(curve, index=bars.index), equity


def performance(curve: pd.Series, trades: pd.DataFrame, final_equity: float) -> dict[str, float | int]:
    """Calculate compounded return, mark-to-market drawdown and trade quality."""
    if curve.empty:
        return {"return_%": 0.0, "max_drawdown_%": 0.0, "trades": 0, "win_rate_%": 0.0, "profit_factor": 0.0}
    days = max((curve.index[-1] - curve.index[0]).total_seconds() / 86400, 1)
    cagr = ((final_equity ** (365.25 / days)) - 1) * 100 if final_equity > 0 else -100.0
    winners = trades.loc[trades["ret_net"] > 0, "ret_net"] if not trades.empty else pd.Series(dtype=float)
    losers = trades.loc[trades["ret_net"] < 0, "ret_net"] if not trades.empty else pd.Series(dtype=float)
    pf = winners.sum() / abs(losers.sum()) if len(losers) else float("inf") if len(winners) else 0.0
    return {
        "return_%": (final_equity - 1) * 100,
        "CAGR_%": cagr,
        "max_drawdown_%": float((curve / curve.cummax() - 1).min() * 100),
        "trades": len(trades),
        "win_rate_%": float((trades["ret_net"] > 0).mean() * 100) if not trades.empty else 0.0,
        "profit_factor": float(pf),
    }


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to generate one-minute candles.")
    minute = pd.read_parquet(MINUTE_DATA)
    h4 = aggregate_bars(minute, "4h", 216)
    m15 = aggregate_bars(minute, "15min", 13)
    blocks = build_blocks(h4)

    signals: dict[pd.Timestamp, dict[str, object]] = {}
    for timestamp, bar in m15.iterrows():
        signal = rejection_signal(timestamp, bar, blocks)
        if signal is not None:
            signals[timestamp] = signal

    segments = m15.index.to_series().diff().gt(pd.Timedelta(minutes=15)).cumsum()
    all_trades: list[pd.DataFrame] = []
    all_curves: list[pd.Series] = []
    equity = 1.0
    for _, segment in m15.groupby(segments):
        trades, curve, equity = simulate_segment(segment, signals, equity)
        if not trades.empty:
            all_trades.append(trades)
        all_curves.append(curve)

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    curve = pd.concat(all_curves).sort_index() if all_curves else pd.Series(dtype=float)
    report_dir = ROOT / "data/reports"
    parquet_dir = ROOT / "data/parquet"
    report_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    zone_path = report_dir / "luxalgo_internal_4h_order_blocks.csv"
    trade_path = report_dir / "luxalgo_ob_15m_trades.csv"
    equity_path = report_dir / "luxalgo_ob_15m_equity.csv"
    blocks_df = pd.DataFrame([asdict(block) for block in blocks])
    blocks_df.to_csv(zone_path, index=False)
    trades.to_csv(trade_path, index=False)
    curve.rename("equity").to_csv(equity_path, index_label="time")
    h4.to_parquet(parquet_dir / "BTCUSD_4h_20260101_20261026.parquet", compression="zstd")
    m15.to_parquet(parquet_dir / "BTCUSD_15m_20260101_20261026.parquet", compression="zstd")

    print("=== LuxAlgo internal 4h OB -> 15m rejection backtest ===")
    print(f"4h bars: {len(h4):,}; 15m bars: {len(m15):,}; confirmed internal OBs: {len(blocks)}")
    print(f"Data: {m15.index.min()} to {m15.index.max()} UTC; incomplete market-data bins omitted")
    print("Entry: zone touch and 15m close back outside; fill next 15m open")
    print("Initial SL: 2x rejection-candle range; initial target: 2R trigger, then trail SL")
    print("Trail: after 2R, favorable extreme minus/plus 2x completed 15m candle range")
    print(f"Fees: {FEE_PER_SIDE:.4%} per side; no slippage or funding; long and short")
    print("\nPerformance:")
    for key, value in performance(curve, trades, equity).items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    if not trades.empty:
        print("\nTrades:")
        print(trades.to_string(index=False))
    else:
        print("No trades passed the order-block rejection rules.")
    print(f"\nZones:   {zone_path.relative_to(ROOT)}")
    print(f"Trades:  {trade_path.relative_to(ROOT)}")
    print(f"Equity:  {equity_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
