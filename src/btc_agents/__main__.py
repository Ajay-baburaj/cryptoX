"""CLI for the BTC multi-timeframe lab."""
import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

import pandas as pd
import requests

from . import data, news
from .agents import decide, trigger
from .context import add_context
from .features import features
from .replay import (Market, ReplayConfig, candidate_from, forecast_report, risk_plan, run, scorecard,
                     signal_candidates, walk_forward)

BASE = Path("data/btc_agents")
BINANCE = Path("data/binance_ob_timeframes")
DELTA = Path("data/parquet/BTCUSD_1m_20260101_20261026.parquet")
NEWS_DB = BASE / "news.sqlite3"


def stamp(value):
    value = pd.Timestamp(value)
    if pd.isna(value):
        raise ValueError("An actual UTC timestamp is required")
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def inputs(args):
    if args.minutes:
        minutes = data.minute_file(args.minutes)
    elif args.venue == "binance":
        minutes = data.local_binance(BINANCE / "raw")
    else:
        minutes = data.minute_file(DELTA)
    if args.flow_minutes:
        minutes = data.attach_trade_flow(minutes, data.minute_file(args.flow_minutes))
    funding_path = args.funding
    if funding_path is None and args.venue == "binance" and args.minutes is None:
        funding_path = BINANCE / "funding.parquet"
    funding = data.funding_file(funding_path)
    return minutes, funding


def matrix_for(minutes, funding, args):
    return add_context(features(minutes), args.context, args.events, args.news_db, funding,
                       f"{args.venue}_settled_funding")


def backtest(args):
    minutes, funding = inputs(args)
    fills, settlements, execution_venue = minutes, funding, args.venue
    if args.execution_minutes:
        if not args.execution_venue:
            raise ValueError("--execution-minutes requires --execution-venue")
        fills = data.minute_file(args.execution_minutes)
        settlements = data.funding_file(args.execution_funding)
        execution_venue = args.execution_venue
    elif args.execution_venue or args.execution_funding:
        raise ValueError("Execution overrides require --execution-minutes")
    first_minute = max(minutes.index[0], fills.index[0])
    start = stamp(args.start) if args.start else first_minute
    last_close = min(minutes.index[-1], fills.index[-1]) + pd.Timedelta(minutes=1)
    end = stamp(args.end) if args.end else last_close
    if not first_minute <= start < end <= last_close:
        raise ValueError("Replay dates must be within both signal and execution minute history")
    config = ReplayConfig(args.equity, args.risk, args.fee_bps, args.friction_bps,
                          delay_minutes=args.delay_minutes)
    selected_minutes = minutes.loc[minutes.index < end]
    matrix = matrix_for(selected_minutes, funding, args).loc[lambda frame: frame.index >= start]
    if args.execution_minutes:
        # Translate reference levels using prices observable at the decision.
        fill_reference = fills.close.reindex(matrix.index - pd.Timedelta(minutes=1))
        matrix["execution_reference"] = fill_reference.to_numpy()
        matrix = matrix.dropna(subset=["execution_reference"])
    if matrix.empty:
        raise ValueError("No complete decision bars in the replay interval")
    market = Market(fills.loc[fills.index < end], settlements)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    matrix.to_parquet(output / "features.parquet")
    with (output / "decisions.jsonl").open("w") as decision_log:
        candidates = signal_candidates(matrix, ablations=args.ablations, log=decision_log)
    summaries, by_regime, audits = [], [], []
    for arm, entries in candidates.items():
        audit = []
        trades = run(market, entries, start, end, config, audit=audit)
        trades.to_csv(output / f"trades_{arm}.csv", index=False)
        summaries.append({"arm": arm, "candidates": len(entries), **scorecard(trades, start, end, config.equity)})
        for name, subset in trades.groupby("regime"):
            by_regime.append({"arm": arm, "regime": name, **scorecard(subset, start, end, config.equity)})
        audits.extend((arm, stamp_, reason) for stamp_, reason in audit)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output / "scorecard.csv", index=False)
    pd.DataFrame(by_regime, columns=["arm", "regime", *summary.columns[2:]]).to_csv(
        output / "by_regime.csv", index=False)
    pd.DataFrame(audits, columns=["arm", "decision_at", "reason"]).to_csv(output / "execution_audit.csv", index=False)
    forecast_report(market, candidates, start, end, config.delay_minutes).to_csv(
        output / "forecasts.csv", index=False)
    if args.walk_forward:
        folded = walk_forward(market, candidates, start, end, config)
        if folded.empty:
            print("No full six-month training plus two-month test window.", file=sys.stderr)
        folded.to_csv(output / "walk_forward.csv", index=False)
    window_minutes = minutes.loc[(minutes.index >= start) & (minutes.index < end)]
    expected = int((end.ceil("min") - start.ceil("min")) / pd.Timedelta(minutes=1))
    metadata = {
        "signal_venue": args.venue, "execution_venue": execution_venue,
        "start": str(start), "end_exclusive": str(end),
        "minute_rows": len(window_minutes), "expected_minutes": expected, "decision_bars": len(matrix),
        "execution_minute_rows": int(((fills.index >= start) & (fills.index < end)).sum()),
        "flow_minute_rows": int(window_minutes.taker_buy_volume.notna().sum())
        if "taker_buy_volume" in window_minutes else 0,
        "funding_events_in_window": int(((settlements.index >= start) & (settlements.index < end)).sum())
        if settlements is not None else 0,
        "funding_supplied": settlements is not None,
        "parameters": vars(config), "walk_forward": args.walk_forward, "ablations": args.ablations,
        "news_db": str(args.news_db) if args.news_db else None,
        "context_csv": str(args.context) if args.context else None,
        "event_calendar_csv": str(args.events) if args.events else None,
    }
    (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if not metadata["funding_events_in_window"]:
        print("No settlement events in the run. Scores omit funding.", file=sys.stderr)
    print(summary[["arm", "candidates", "trades", "unresolved", "mark_inclusive_net_pct"]].to_string(index=False))
    print(f"Reports written to {output}")


def latest(args):
    as_of = stamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    if args.live:
        if args.as_of or args.minutes or args.venue != "delta":
            raise ValueError("--live uses --venue delta and the current public feed")
        end = as_of.floor("min")
        start = end - pd.Timedelta(days=22)
        cached = BASE / "current_delta.parquet"
        if cached.exists():
            previous = data.minute_file(cached)
            if previous.index[0] <= start + pd.Timedelta(minutes=5):
                start = max(start, min(end - pd.Timedelta(minutes=5), previous.index[-1]))
        data.download_delta(start, end, cached)
        args.minutes = cached
    minutes, funding = inputs(args)
    minutes = minutes.loc[minutes.index + pd.Timedelta(minutes=1) <= as_of]
    matrix = matrix_for(minutes, funding, args)
    row = matrix.iloc[-1]
    if row.name != as_of.floor("5min"):
        print(json.dumps({"action": "FLAT", "reason": "latest_5m_candle_missing_or_stale",
                          "source_close": row.name.isoformat(), "as_of": as_of.isoformat()}))
        return
    decision = decide(row)
    payload = decision.model_dump(mode="json")
    from .dashboard import details
    observed = minutes.index[-1] + pd.Timedelta(minutes=1)
    context_row = add_context(pd.DataFrame(index=[observed]), args.context, args.events, args.news_db, funding).iloc[0]
    live_row = row.copy()
    live_row.update(context_row)
    payload.update(details(minutes, live_row))
    payload["market"] = {}
    for label, prefix in (("4h", "h4"), ("1h", "h1"), ("15m", "m15"), ("5m", "m5")):
        atr_pct = row.get(f"{prefix}_atr_pct")
        payload["market"][label] = {
            "trend": row.get(f"{prefix}_trend") if pd.notna(row.get(f"{prefix}_trend")) else "unknown",
            "volatility": row.get(f"{prefix}_volatility") if pd.notna(row.get(f"{prefix}_volatility")) else "unknown",
            "atr_pct": float(atr_pct) if pd.notna(atr_pct) else None,
        }
    if decision.risk_multiplier:
        trigger_result, side = trigger(row)
        candidate = replace(candidate_from(row, trigger_result, side), size=decision.risk_multiplier)
        config = ReplayConfig(args.equity, args.risk, args.fee_bps, args.friction_bps)
        reference = row.m5_close * (1 + side * config.friction_bps / 10_000)
        plan = risk_plan(candidate, reference, config.equity, config)
        if plan is None:
            payload.update(action="FLAT", reason="estimated_risk_plan_rejected", risk_multiplier=0)
        else:
            stop, target, notional, risk = plan
            payload["estimated_risk"] = {"reference_price": reference, "stop": stop, "target": target,
                                         "notional": notional, "planned_max_loss": risk}
    print(json.dumps(payload, indent=2))


def loop(work, every):
    while True:
        ok = work()
        if not every:
            return 0 if ok else 1
        time.sleep(every)


def news_command(args):
    def poll_once():
        outcome = news.poll(args.db, args.sources.split(","), args.gdelt_query)
        print(json.dumps(outcome), flush=True)
        return any("received" in row for row in outcome.values())
    return loop(poll_once, args.every)


def derivatives_command(args):
    def poll_once():
        observations, failures = data.derivatives_snapshot()
        if observations:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("a", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["available_at", "metric", "value", "source"])
                if stream.tell() == 0:
                    writer.writeheader()
                writer.writerows(observations)
        print(json.dumps({"observations": len(observations), "errors": failures}), flush=True)
        return bool(observations)
    return loop(poll_once, args.every)


def download_command(args):
    if args.output.suffix != ".parquet":
        raise ValueError("Use a .parquet output path")
    frame = data.download_delta(stamp(args.start), stamp(args.end) if args.end else pd.Timestamp.now(tz="UTC"),
                                args.output)
    print(f"{len(frame):,} Delta BTCUSD minutes in {args.output}")


def funding_command(args):
    if args.output.suffix != ".csv":
        raise ValueError("Use a .csv output path")
    events = data.download_delta_funding(stamp(args.start), stamp(args.end) if args.end else pd.Timestamp.now(tz="UTC"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.output, index=False)
    print(f"{len(events):,} Delta BTCUSD settlement rates in {args.output}")


def open_interest_command(args):
    if args.output.suffix != ".csv":
        raise ValueError("Use a .csv output path")
    events = data.download_delta_open_interest(stamp(args.start), stamp(args.end) if args.end else pd.Timestamp.now(tz="UTC"))
    if events.empty:
        raise ValueError("No consecutive open-interest observations in the interval")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.output, index=False)
    print(f"{len(events):,} Delta BTCUSD hourly open-interest changes in {args.output}")


def import_command(args):
    if args.output.suffix != ".parquet":
        raise ValueError("Use a .parquet output path")
    minutes = (data.local_binance if args.venue == "binance" else data.local_delta)(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    minutes.to_parquet(args.output)
    print(f"{len(minutes):,} {args.venue} minutes in {args.output}")


def add_inputs(parser):
    parser.add_argument("--venue", choices=("binance", "delta"), default="binance")
    parser.add_argument("--minutes", type=Path, help="Custom UTC minute-open parquet or CSV from the selected venue")
    parser.add_argument("--flow-minutes", type=Path, help="Optional same-venue trade-built bars with taker volume")
    parser.add_argument("--funding", type=Path, help="Settlement history for the selected execution venue")
    parser.add_argument("--context", type=Path, help="Point-in-time context CSV")
    parser.add_argument("--events", type=Path, help="Known-in-advance macro event CSV")
    parser.add_argument("--news-db", type=Path, default=NEWS_DB)


def add_risk_args(parser):
    parser.add_argument("--fee-bps", type=float, default=5.9, help="Trading fee per side")
    parser.add_argument("--friction-bps", type=float, default=4.1, help="Spread and slippage per side")
    parser.add_argument("--equity", type=float, default=10_000)
    parser.add_argument("--risk", type=float, default=.005, help="Per-trade equity fraction")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("backtest", help="Replay the rule-based strategy and comparisons")
    add_inputs(replay)
    add_risk_args(replay)
    replay.add_argument("--execution-venue", choices=("binance", "delta"))
    replay.add_argument("--execution-minutes", type=Path, help="Replay fills on a distinct minute series")
    replay.add_argument("--execution-funding", type=Path, help="Funding settlements for overridden fill venue")
    replay.add_argument("--start", help="UTC start, inclusive")
    replay.add_argument("--end", help="UTC end, exclusive")
    replay.add_argument("--output", type=Path, default=BASE / "backtest")
    replay.add_argument("--delay-minutes", type=int, default=1)
    replay.add_argument("--walk-forward", action="store_true")
    replay.add_argument("--ablations", action="store_true")
    replay.set_defaults(handler=backtest)

    signal = sub.add_parser("signal", help="Preview a decision from the latest complete 5m close")
    add_inputs(signal)
    add_risk_args(signal)
    signal.add_argument("--live", action="store_true", help="Refresh public Delta candles for the current 5m decision")
    signal.add_argument("--as-of", help="Point-in-time UTC replay for a saved dataset")
    signal.set_defaults(handler=latest)

    collect = sub.add_parser("news", help="Collect keyless RSS and optional GDELT news")
    collect.add_argument("--db", type=Path, default=NEWS_DB)
    collect.add_argument("--sources", default=",".join(news.FEEDS))
    collect.add_argument("--gdelt-query", default="bitcoin sourcelang:english")
    collect.add_argument("--every", type=int, default=0, help="Seconds between polls, 0 for one poll")
    collect.set_defaults(handler=news_command)

    derivatives = sub.add_parser("derivatives", help="Poll public Delta and Binance context")
    derivatives.add_argument("--output", type=Path, default=BASE / "derivatives.csv")
    derivatives.add_argument("--every", type=int, default=0, help="Seconds between polls, 0 for one poll")
    derivatives.set_defaults(handler=derivatives_command)

    candles = sub.add_parser("delta-candles", help="Download 1m BTCUSD candles from Delta India")
    candles.add_argument("--start", required=True)
    candles.add_argument("--end")
    candles.add_argument("--output", type=Path, default=BASE / "delta_minutes.parquet")
    candles.set_defaults(handler=download_command)

    funding = sub.add_parser("delta-funding", help="Download historical BTCUSD funding settlements")
    funding.add_argument("--start", required=True)
    funding.add_argument("--end")
    funding.add_argument("--output", type=Path, default=BASE / "delta_funding.csv")
    funding.set_defaults(handler=funding_command)

    oi = sub.add_parser("delta-oi", help="Download historical hourly BTCUSD open-interest changes")
    oi.add_argument("--start", required=True)
    oi.add_argument("--end")
    oi.add_argument("--output", type=Path, default=BASE / "delta_oi.csv")
    oi.set_defaults(handler=open_interest_command)

    importer = sub.add_parser("import-archives", help="Convert Binance or Delta ZIPs to flow-aware 1m parquet")
    importer.add_argument("--venue", choices=("binance", "delta"), required=True)
    importer.add_argument("--directory", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    importer.set_defaults(handler=import_command)

    args = parser.parse_args(argv)
    if args.command == "news" and set(args.sources.split(",")) - {*news.FEEDS, "gdelt"}:
        parser.error("Unknown news source. Use: " + ", ".join([*news.FEEDS, "gdelt"]))
    if getattr(args, "every", 0) != 0 and args.every < 60:
        parser.error("--every must be 0 or at least 60 seconds")
    try:
        return args.handler(args) or 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, requests.RequestException) as error:
        parser.exit(1, f"btc_agents: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
