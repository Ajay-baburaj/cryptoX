"""Order-block rejection research: which zones, filters and exits hold up out of sample.

Same method as the OptionX NIFTY research: score a grid of variants, split chronologically
(train Jan-May 2026, test Jul-Oct 2026; June is missing from the archive), and call a setting
robust only if it is profitable with >= 60% wins in BOTH halves. Families of settings are judged
by the share of their exit variants that are robust, not by the single best row, because the
top-on-train rows repeatedly failed on test.

Finally a null test: the chosen strategy's trades are replayed at random 15m bars that pass the
same trend/ADX filter, with the same side, stop distance and target, to see whether the order
blocks add anything beyond the filter and the small-target geometry.

    .venv/bin/python scripts/research_ob_rejection.py
"""
from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.ob_rejection import (
    FEE_PER_SIDE,
    EventConfig,
    ExitConfig,
    MinutePath,
    StrategyConfig,
    aggregate,
    clean_minutes,
    exit_outcomes,
    htf_trend,
    indicators,
    rejection_events,
    simulate,
    strategy_events,
    take_sequential,
    walk_exit,
)


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")
EVENT_SETS = {  # name: (OB timeframes in minutes, entry timeframe)
    "30m->5m": ((30,), 5),
    "1h->5m": ((60,), 5),
    "1h->15m": ((60,), 15),
    "2h->15m": ((120,), 15),
    "1h+4h->15m": ((240, 60), 15),
}
TRENDS = ("none", "ema200", "ema50", "h1_ema200")
ADX_MAX = (20, 25, 30, 999)
STOP_BUFFERS = (0.25, 0.5)
TARGETS_R = (0.5, 0.6, 0.75, 1.0)
NULL_DRAWS = 300


def load_events(minutes: pd.DataFrame, ob_list: tuple[int, ...], entry: int, rule: str) -> pd.DataFrame:
    frames = [rejection_events(minutes, EventConfig(ob, entry, rule)) for ob in ob_list]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True).drop_duplicates("signal_time").sort_values("signal_time").reset_index(drop=True)


def trend_mask(events: pd.DataFrame, trend: str) -> pd.Series:
    if trend == "none":
        return pd.Series(True, index=events.index)
    column = {"ema200": "ema200_dir", "ema50": "ema50_dir", "h1_ema200": "h1_ema200_dir"}[trend]
    return events["side"] == events[column]


def score(events: pd.DataFrame, rets: np.ndarray, r_mult: np.ndarray, taken: np.ndarray) -> dict[str, float | int]:
    frame = pd.DataFrame({
        "month": events["entry_time"].iloc[taken].dt.strftime("%Y-%m").to_numpy(),
        "ret": rets[taken],
        "R": r_mult[taken],
    })
    frame["win"] = frame["ret"] > 0
    by_month = frame.groupby("month").agg(win=("win", "mean"), ret=("ret", "sum"))
    train, test = frame[frame["month"] < "2026-06"], frame[frame["month"] >= "2026-06"]
    return {
        "trades": len(frame),
        "win_%": frame["win"].mean() * 100,
        "net_%": frame["ret"].sum() * 100,
        "R": frame["R"].sum(),
        "train_trades": len(train),
        "train_win_%": train["win"].mean() * 100 if len(train) else np.nan,
        "train_net_%": train["ret"].sum() * 100,
        "test_trades": len(test),
        "test_win_%": test["win"].mean() * 100 if len(test) else np.nan,
        "test_net_%": test["ret"].sum() * 100,
        "months": len(by_month),
        "months_win60": int((by_month["win"] >= 0.6).sum()),
        "months_up": int((by_month["ret"] > 0).sum()),
        "worst_month_%": by_month["ret"].min() * 100,
    }


def null_test(minutes: pd.DataFrame, path: MinutePath, config: StrategyConfig, trades: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Win rate and net of the same trades placed at random filter-passing 15m bars."""
    bars = aggregate(minutes, config.entry_minutes)
    ind = indicators(bars)
    adx_ok = htf_trend(minutes, bars.index)["h4_adx"] <= config.max_h4_adx
    pools = {
        1: bars.index[((bars["close"] > ind["ema200"]) & adx_ok).to_numpy()],
        -1: bars.index[((bars["close"] < ind["ema200"]) & adx_ok).to_numpy()],
    }
    rng = np.random.default_rng(7)
    wins, nets = [], []
    for _ in range(NULL_DRAWS):
        rets = []
        for trade in trades.to_dict("records"):
            side = 1 if trade["side"] == "long" else -1
            pool = pools[side]
            start = path.start(pool[rng.integers(len(pool))])  # bar close = next bar's open
            if start >= len(path.ns) - 1:
                continue
            entry = path.open[start]
            risk = trade["risk_%"] / 100 * entry
            _, fill, _ = walk_exit(path, start, side, entry, entry - side * risk,
                                   entry + side * config.exit.target_r * risk, config.exit.max_hours * 60)
            rets.append((1 - FEE_PER_SIDE) ** 2 * (1 + side * (fill - entry) / entry) - 1)
        rets_arr = np.array(rets)
        wins.append((rets_arr > 0).mean())
        nets.append(rets_arr.sum())
    return np.array(wins), np.array(nets)


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to generate one-minute candles.")
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    path = MinutePath(minutes)

    rows: list[dict[str, object]] = []
    for (set_name, (ob_list, entry)), rule in product(EVENT_SETS.items(), ("wick", "inside")):
        events = load_events(minutes, ob_list, entry, rule)
        masks = {
            (trend, adx_max): (trend_mask(events, trend) & (events["h4_adx"] <= adx_max)).to_numpy()
            for trend, adx_max in product(TRENDS, ADX_MAX)
        }
        for buffer, target in product(STOP_BUFFERS, TARGETS_R):
            starts, ends, rets, r_mult = exit_outcomes(events, path, ExitConfig("zone", buffer, target, 96))
            for (trend, adx_max), mask in masks.items():
                taken = take_sequential(starts, ends, rets, mask)
                if len(taken) < 20:
                    continue
                rows.append({
                    "events": set_name, "rule": rule, "trend": trend,
                    "max_h4_adx": adx_max if adx_max < 999 else None,
                    "stop_buffer_atr": buffer, "target_R": target,
                    **score(events, rets, r_mult, taken),
                })
        print(f"scored {set_name} {rule}", flush=True)

    results = pd.DataFrame(rows)
    results["robust"] = (
        (results["train_net_%"] > 0) & (results["test_net_%"] > 0)
        & (results["train_win_%"] >= 60) & (results["test_win_%"] >= 60)
    )
    out_path = ROOT / "data/reports/ob_rejection_research.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"\n=== {len(results)} settings; train Jan-May, test Jul-Oct 2026; robust = both halves net>0 and win>=60% ===")
    print("\nShare of exit variants that are robust (rows: events/rule/trend, columns: max 4h ADX; 999 = no ADX filter):")
    share = results.assign(adx=results["max_h4_adx"].fillna(999)).pivot_table(
        index=["events", "rule", "trend"], columns="adx", values="robust", aggfunc="mean")
    print(share.round(2).to_string())

    columns = ["events", "rule", "trend", "max_h4_adx", "stop_buffer_atr", "target_R", "trades", "win_%", "net_%",
               "train_win_%", "test_win_%", "train_net_%", "test_net_%", "months_win60", "months_up", "worst_month_%"]
    print("\nTop 10 by TRAIN net (what naive tuning would pick) and how they did on test:")
    print(results.sort_values("train_net_%", ascending=False)[columns].head(10).round(2).to_string(index=False))
    print("\nRobust settings with the most months at >=60% wins:")
    robust = results[results["robust"]].sort_values(["months_win60", "months_up", "net_%"], ascending=False)
    print(robust[columns].head(15).round(2).to_string(index=False))

    config = StrategyConfig()
    trades = simulate(strategy_events(minutes, config), path, config.exit)
    wins, nets = null_test(minutes, path, config, trades)
    win_rate, net = (trades["ret_net"] > 0).mean(), trades["ret_net"].sum()
    print("\n=== Null test for the chosen strategy (make ob-rejection-backtest) ===")
    print(f"Strategy: {len(trades)} trades, win {win_rate:.1%}, net {net:+.2%} at 1x notional")
    print(f"Random filter-passing entries, same side/stop/target ({NULL_DRAWS} draws): "
          f"win {wins.mean():.1%} (95th pct {np.quantile(wins, 0.95):.1%}), net {nets.mean():+.2%} (95th pct {np.quantile(nets, 0.95):+.2%})")
    print(f"Share of random draws matching the strategy: win {(wins >= win_rate).mean():.3f}, net {(nets >= net).mean():.3f}")
    print(f"\nFull grid: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
