"""Backtest the EMA200/RSI50/engulfing strategy on local Delta trade archives."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from strategy.ema_rsi_engulfing import Params, compute, simulate, summary


ROOT = Path(__file__).resolve().parents[1]


def load_trade_archives(data_dir: Path, chunk_size: int = 500_000) -> tuple[pd.DataFrame, dict[str, int]]:
    """Convert monthly Delta public trade CSV zips to one-minute UTC OHLCV bars."""
    archives = sorted(data_dir.glob("futures-trades-monthly-BTCUSD-2026-*.csv.zip"))
    if not archives:
        raise FileNotFoundError(f"No BTCUSD monthly trade zips found in {data_dir}")

    monthly_bars: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for archive in archives:
        print(f"Reading {archive.name} ...", flush=True)
        partials: list[pd.DataFrame] = []
        row_count = 0
        previous_timestamp: pd.Timestamp | None = None
        with ZipFile(archive) as zipped:
            csv_names = [name for name in zipped.namelist() if name.endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in {archive.name}, found {len(csv_names)}")
            with zipped.open(csv_names[0]) as csv_file:
                chunks = pd.read_csv(
                    csv_file,
                    usecols=["price", "size", "timestamp"],
                    chunksize=chunk_size,
                )
                for chunk in chunks:
                    chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], utc=True, errors="coerce")
                    chunk["price"] = pd.to_numeric(chunk["price"], errors="coerce")
                    chunk["size"] = pd.to_numeric(chunk["size"], errors="coerce")
                    chunk = chunk.dropna(subset=["timestamp", "price", "size"])
                    if chunk.empty:
                        continue
                    if previous_timestamp is not None and chunk["timestamp"].iloc[0] < previous_timestamp:
                        raise ValueError(f"Trade timestamps are out of order in {archive.name}")
                    previous_timestamp = chunk["timestamp"].iloc[-1]
                    row_count += len(chunk)
                    chunk["minute"] = chunk["timestamp"].dt.floor("min")
                    bars = chunk.groupby("minute", sort=False).agg(
                        open=("price", "first"),
                        high=("price", "max"),
                        low=("price", "min"),
                        close=("price", "last"),
                        volume=("size", "sum"),
                    )
                    partials.append(bars)
        if not partials:
            counts[archive.name] = 0
            continue
        month = pd.concat(partials).groupby(level=0).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        monthly_bars.append(month)
        counts[archive.name] = row_count
        print(f"  {row_count:,} trades -> {len(month):,} minute bars", flush=True)

    if not monthly_bars:
        raise ValueError("No valid trades found in the archives")
    all_bars = pd.concat(monthly_bars).sort_index()
    if all_bars.index.has_duplicates:
        all_bars = all_bars.groupby(level=0).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    return all_bars, counts


def backtest_segments(bars: pd.DataFrame, params: Params, fee_per_side: float) -> pd.DataFrame:
    """Backtest separately across data outages so positions never cross a large gap."""
    boundaries = bars.index.to_series().diff().gt(pd.Timedelta(minutes=5)).cumsum()
    results: list[pd.DataFrame] = []
    for _, segment in bars.groupby(boundaries):
        if len(segment) < params.ema_len + 2:
            print(f"Skipping short segment ({len(segment)} bars)", flush=True)
            continue
        signals = compute(segment, params)
        trades = simulate(signals, fee_per_side=fee_per_side)
        if not trades.empty:
            results.append(trades)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def save_equity_curve(trades: pd.DataFrame, out_path: Path) -> None:
    """Save compounded per-trade equity points to CSV."""
    if trades.empty:
        pd.DataFrame(columns=["time", "equity"]).to_csv(out_path, index=False)
        return
    curve = pd.DataFrame({
        "time": trades["exit_time"],
        "equity": (1 + trades["ret_net"]).cumprod(),
    })
    curve.to_csv(out_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--fee-per-side", type=float, default=0.00059)
    parser.add_argument("--allow-shorts", action="store_true")
    parser.add_argument("--stop-mode", choices=["entry", "candle_low"], default="entry")
    args = parser.parse_args()

    bars, counts = load_trade_archives(args.data_dir)
    output_dir = ROOT / "data/parquet"
    output_dir.mkdir(parents=True, exist_ok=True)
    start = bars.index.min().strftime("%Y%m%d")
    end = bars.index.max().strftime("%Y%m%d")
    bars_path = output_dir / f"BTCUSD_1m_{start}_{end}.parquet"
    bars.to_parquet(bars_path, compression="zstd")

    params = Params(allow_shorts=args.allow_shorts, stop_mode=args.stop_mode)
    trades = backtest_segments(bars, params, args.fee_per_side)
    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trades_path = report_dir / "ema_rsi_engulfing_trades.csv"
    equity_path = report_dir / "ema_rsi_engulfing_equity.csv"
    trades.to_csv(trades_path, index=False)
    save_equity_curve(trades, equity_path)

    print("\n=== EMA200 + RSI50 + Engulfing backtest ===")
    print(f"Data:       {bars.index.min()} to {bars.index.max()} (UTC)")
    print(f"Bars:       {len(bars):,} one-minute bars from {len(counts)} archives")
    print("Archives:   " + ", ".join(
        f"{name.split('BTCUSD-')[-1].removesuffix('.csv.zip')}: {count:,} trades"
        for name, count in counts.items()
    ))
    print("Coverage:")
    for month, month_bars in bars.groupby(bars.index.strftime("%Y-%m")):
        print(f"  {month}: {month_bars.index.min()} to {month_bars.index.max()} ({len(month_bars):,} bars)")
    gaps = bars.index.to_series().diff()
    major_gaps = gaps[gaps > pd.Timedelta(minutes=5)]
    if not major_gaps.empty:
        print(f"Data gaps over 5 minutes: {len(major_gaps)}; each gap resets indicators and closes any open trade at the prior bar.")
    print(f"Fees:       {args.fee_per_side:.4%} per side ({args.fee_per_side * 2:.4%} round trip)")
    print(f"Shorts:     {'enabled' if params.allow_shorts else 'disabled'}")
    print(f"Stop mode:  {params.stop_mode}")
    metrics = summary(trades)
    if not trades.empty:
        wins = trades.loc[trades["ret_net"] > 0, "ret_net"]
        losses = trades.loc[trades["ret_net"] < 0, "ret_net"]
        profit_factor = wins.sum() / abs(losses.sum()) if not losses.empty else float("inf")
        print(f"Trades:     {metrics['trades']}")
        print(f"Win rate:   {metrics['win_rate']:.1%}")
        print(f"Net return: {metrics['total_net_%']:.2f}% (compounded, 100% notional per trade)")
        print(f"Avg trade:  {metrics['avg_net_%']:.3f}% net")
        print(f"Max DD:     {metrics['max_dd_%']:.2f}% (trade-level equity curve)")
        print(f"Profit fac: {profit_factor:.2f}")
        print(f"TP / SL / EOD: {(trades['reason'] == 'TP').sum()} / {(trades['reason'] == 'SL').sum()} / {(trades['reason'] == 'EOD').sum()}")
        print("\nFirst 5 trades:")
        print(trades.head().to_string(index=False))
    else:
        print("No trades were generated with these settings.")
    print(f"\nMinute bars: {bars_path.relative_to(ROOT)}")
    print(f"Trade list:  {trades_path.relative_to(ROOT)}")
    print(f"Equity:      {equity_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
