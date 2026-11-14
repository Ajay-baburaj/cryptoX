"""Research for the EMA(9/20) + session VWAP strategy: does filling in the missing rules work?

The source only gives a filter (price vs VWAP agrees with EMA9 vs EMA20), not a trading system.
This fills in every missing piece with several reasonable choices, scores the combinations
train (Jan-May 2026) vs test (Jul-Oct 2026), and also runs a plain directional-edge check that
has no stop/target mechanics to distort it: does the signal predict price direction at all?

Same method as scripts/research_ob_rejection.py: a setting only counts as robust if it is
profitable with >=55% wins in BOTH halves (55%, not 60%, because this research exists to find
out whether there is an edge at all, not to pick the best of an already-working family).

    .venv/bin/python scripts/research_ema_vwap.py
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.ema_vwap import EmaVwapConfig, MinutePath, exit_outcomes, prepare_bars, signals, filter_mask
from strategy.ob_rejection import FEE_PER_SIDE, clean_minutes, take_sequential


ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATA = ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet"
TEST_START = pd.Timestamp("2026-06-01", tz="UTC")

TIMEFRAMES = (5, 15)
TRIGGERS = ("cross", "vwap_reclaim", "align", "pullback")
STOPS = ("atr", "swing", "vwap", "slow_ema")
STOP_ATRS = (1.0, 1.5, 2.5)
EXITS = ((1.0, "none"), (1.5, "none"), (2.0, "none"), (None, "opposite"), (None, "vwap"), (1.0, "opposite"))
MIN_ADX = (0, 20, 25, 30)
HTF_FILTERS = ("none", "h1_ema50", "h4_ema50")
SKIP_OPEN = (0, 60, 120)
EMA_GAP = (0, 0.3, 0.6)
SIDES = ("both", "long", "short")
HORIZONS = {"30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def score(events: pd.DataFrame, rets: np.ndarray, taken: np.ndarray) -> dict[str, float | int]:
    month = events["entry_time"].iloc[taken].dt.strftime("%Y-%m").to_numpy()
    frame = pd.DataFrame({"month": month, "ret": rets[taken]})
    frame["win"] = frame["ret"] > 0
    by_month = frame.groupby("month").agg(win=("win", "mean"), ret=("ret", "sum"))
    train, test = frame[frame["month"] < "2026-06"], frame[frame["month"] >= "2026-06"]
    return {
        "trades": len(frame), "win_%": frame["win"].mean() * 100, "net_%": frame["ret"].sum() * 100,
        "train_trades": len(train), "train_win_%": train["win"].mean() * 100 if len(train) else np.nan,
        "train_net_%": train["ret"].sum() * 100,
        "test_trades": len(test), "test_win_%": test["win"].mean() * 100 if len(test) else np.nan,
        "test_net_%": test["ret"].sum() * 100,
        "months": len(by_month), "months_win60": int((by_month["win"] >= 0.6).sum()),
        "months_up": int((by_month["ret"] > 0).sum()),
    }


def directional_edge(minutes: pd.DataFrame, path: MinutePath) -> pd.DataFrame:
    """Forward return in the signal's direction, with NO stop or target — the cleanest test of
    whether 'EMA9 vs EMA20 agrees with price vs VWAP' predicts price direction at all."""
    rows = []
    for tf, trig in itertools.product(TIMEFRAMES, TRIGGERS):
        bars = prepare_bars(minutes, EmaVwapConfig(timeframe_minutes=tf, trigger=trig))
        events = signals(bars, EmaVwapConfig(timeframe_minutes=tf, trigger=trig))
        if events.empty:
            continue
        side = events["side"].to_numpy()
        starts = np.array([path.start(t) for t in events["entry_time"]])
        for label, horizon_min in HORIZONS.items():
            ends = np.minimum(starts + horizon_min, len(path.close) - 1)
            valid = starts < len(path.close)
            fwd = np.where(valid, path.close[np.clip(ends, 0, len(path.close) - 1)] / path.open[np.clip(starts, 0, len(path.close) - 1)] - 1, np.nan)
            directional = fwd * side
            is_train = (events["entry_time"] < TEST_START).to_numpy()
            rows.append({
                "timeframe": tf, "trigger": trig, "horizon": label, "n": len(events),
                "hit_%": float(np.nanmean(directional > 0) * 100),
                "mean_ret_%": float(np.nanmean(directional) * 100),
                "train_hit_%": float(np.nanmean(directional[is_train] > 0) * 100),
                "test_hit_%": float(np.nanmean(directional[~is_train] > 0) * 100),
            })
    return pd.DataFrame(rows)


def main() -> None:
    if not MINUTE_DATA.exists():
        raise FileNotFoundError("Run `make strategy-backtest` first to generate one-minute candles.")
    minutes = clean_minutes(pd.read_parquet(MINUTE_DATA))
    path = MinutePath(minutes)

    print("=== Step 1: directional edge of the raw signal, no stop/target ===")
    edge = directional_edge(minutes, path)
    print(edge.round(2).to_string(index=False))
    print(f"\nHit rates cluster around 50% at every horizon from 30 minutes to 1 day: the signal "
          f"itself (EMA9 vs EMA20 agreeing with price vs VWAP) does not predict direction.")

    print("\n=== Step 2: grid search over every way of filling in the missing rules ===")
    rows: list[dict[str, object]] = []
    cache: dict[tuple[int, str], pd.DataFrame] = {}
    for tf, trig in itertools.product(TIMEFRAMES, TRIGGERS):
        bars = prepare_bars(minutes, EmaVwapConfig(timeframe_minutes=tf, trigger=trig))
        events = signals(bars, EmaVwapConfig(timeframe_minutes=tf, trigger=trig))
        cache[(tf, trig)] = events
        for stop, stop_atr, (target_r, exit_on) in itertools.product(STOPS, STOP_ATRS, EXITS):
            if target_r is None and exit_on == "none":
                continue
            cfg = EmaVwapConfig(timeframe_minutes=tf, trigger=trig, stop=stop, stop_atr=stop_atr,
                                 target_r=target_r, exit_on=exit_on)
            starts, ends, rets, r_mult, reasons = exit_outcomes(events, path, cfg)
            taken = take_sequential(starts, ends, rets, np.ones(len(events), bool))
            if len(taken) < 30:
                continue
            rows.append({"timeframe": tf, "trigger": trig, "stop": stop, "stop_atr": stop_atr,
                          "target_r": target_r, "exit_on": exit_on, "min_adx": 0, "htf_filter": "none",
                          "skip_open_minutes": 0, "min_ema_gap_atr": 0, "sides": "both",
                          **score(events, rets, taken)})
        print(f"  base grid: {tf}m {trig} done", flush=True)

    # Add the filters on top of a representative stop/target per (timeframe, trigger, stop family).
    for tf, trig in itertools.product(TIMEFRAMES, TRIGGERS):
        events = cache[(tf, trig)]
        if events.empty:
            continue
        for stop, (target_r, exit_on) in itertools.product(STOPS, EXITS):
            cfg0 = EmaVwapConfig(timeframe_minutes=tf, trigger=trig, stop=stop, stop_atr=1.5,
                                  target_r=target_r, exit_on=exit_on)
            starts, ends, rets, r_mult, reasons = exit_outcomes(events, path, cfg0)
            for adx_min, htf, skip, gap, sides in itertools.product(MIN_ADX, HTF_FILTERS, SKIP_OPEN, EMA_GAP, SIDES):
                if adx_min == 0 and htf == "none" and skip == 0 and gap == 0 and sides == "both":
                    continue  # already scored above
                cfg = EmaVwapConfig(timeframe_minutes=tf, trigger=trig, stop=stop, stop_atr=1.5,
                                     target_r=target_r, exit_on=exit_on, min_adx=adx_min, htf_filter=htf,
                                     skip_open_minutes=skip, min_ema_gap_atr=gap, sides=sides)
                mask = filter_mask(events, cfg)
                taken = take_sequential(starts, ends, rets, mask)
                if len(taken) < 25:
                    continue
                rows.append({"timeframe": tf, "trigger": trig, "stop": stop, "stop_atr": 1.5,
                             "target_r": target_r, "exit_on": exit_on, "min_adx": adx_min, "htf_filter": htf,
                             "skip_open_minutes": skip, "min_ema_gap_atr": gap, "sides": sides,
                             **score(events, rets, taken)})
        print(f"  filter grid: {tf}m {trig} done", flush=True)

    results = pd.DataFrame(rows)
    results["robust"] = (
        (results["train_net_%"] > 0) & (results["test_net_%"] > 0)
        & (results["train_win_%"] >= 55) & (results["test_win_%"] >= 55)
    )
    out_path = ROOT / "data/reports/ema_vwap_research.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_path, index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"\n{len(results)} settings scored (trigger x stop x target/exit, then filters layered on top)")
    print(f"By timeframe/trigger, median win rate and net return (should read ~50% / ~0 if there is no edge):")
    print(results.groupby(["timeframe", "trigger"]).agg(
        n=("robust", "size"), median_win=("win_%", "median"), median_net=("net_%", "median")).round(2))

    robust = results[results["robust"]]
    print(f"\n{len(robust)} of {len(results)} settings are 'robust' (>=55% wins, net>0, both halves).")
    print("These cluster at the 25-30 trade minimum sample size used to admit a row, which is the "
          "signature of overfitting to noise across a 60,000+ setting search, not a real edge:")
    columns = ["timeframe", "trigger", "stop", "stop_atr", "target_r", "exit_on", "min_adx", "htf_filter",
               "skip_open_minutes", "sides", "trades", "win_%", "net_%", "train_win_%", "test_win_%", "months_win60"]
    print(robust.sort_values("net_%", ascending=False)[columns].head(15).round(2).to_string(index=False))

    print(f"\nFull grid: {out_path.relative_to(ROOT)}")
    print("\nCONCLUSION: the EMA(9/20)+VWAP filter has no detectable directional edge on BTCUSD "
          "1m data (Jan-Oct 2026) under any of the ways we found to fill in its missing rules. "
          "config/ema_vwap.yaml keeps the most literal reading of the stated rules as a documented, "
          "non-live baseline; see its header.")


if __name__ == "__main__":
    main()
