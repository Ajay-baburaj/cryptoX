from pathlib import Path

import pandas as pd

from execution.paper_engine import PaperEngine


def make_minutes(last_ts: str, n: int = 5) -> pd.DataFrame:
    index = pd.date_range(end=last_ts, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index)


def make_trades(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for col in ("signal_time", "entry_time", "exit_time"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    return frame


def test_to_frame_indexes_by_minute_and_sorts() -> None:
    engine = PaperEngine(trade_log_path=Path("/tmp/unused_trades.csv"))
    raw = [{"time": 120, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 1},
           {"time": 60, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    frame = engine._to_frame(raw)
    assert list(frame["close"]) == [1, 2]
    assert frame.index[0] == pd.Timestamp("1970-01-01 00:01:00", tz="UTC")


def test_open_position_is_the_trade_still_unresolved_at_the_latest_minute() -> None:
    engine = PaperEngine(trade_log_path=Path("/tmp/unused_trades.csv"))
    engine.minutes = make_minutes("2026-01-01 00:10:00")
    last_minute = engine.minutes.index[-1]
    engine.mark_price = 105.0
    engine.trades = make_trades([{
        "side": "long", "signal_time": "2026-01-01 00:00:00", "entry_time": "2026-01-01 00:01:00",
        "exit_time": last_minute, "entry": 100.0, "exit": 100.0, "stop": 95.0, "target": 110.0,
        "exit_reason": "data_gap", "risk_%": 5.0, "ret_net": 0.0, "r_net": 0.0,
    }])
    position = engine.open_position()
    assert position is not None
    assert position["side"] == "long"
    assert position["mark_price"] == 105.0
    assert position["unrealized_%"] == 5.0  # (105 - 100) / 100 * 100
    assert engine.closed_trades().empty  # the open trade must not double-count as closed


def test_a_trade_resolved_before_the_latest_minute_is_closed_not_open() -> None:
    engine = PaperEngine(trade_log_path=Path("/tmp/unused_trades.csv"))
    engine.minutes = make_minutes("2026-01-01 00:10:00")
    engine.trades = make_trades([{
        "side": "short", "signal_time": "2026-01-01 00:00:00", "entry_time": "2026-01-01 00:01:00",
        "exit_time": "2026-01-01 00:05:00", "entry": 100.0, "exit": 95.0, "stop": 105.0, "target": 90.0,
        "exit_reason": "target", "risk_%": 5.0, "ret_net": 0.05, "r_net": 1.0,
    }])
    assert engine.open_position() is None
    assert len(engine.closed_trades()) == 1


def test_summary_marks_open_position_pnl_into_balance() -> None:
    engine = PaperEngine(starting_balance=1000.0, trade_log_path=Path("/tmp/unused_trades.csv"))
    engine.minutes = make_minutes("2026-01-01 00:10:00")
    last_minute = engine.minutes.index[-1]
    engine.mark_price = 110.0
    engine.trades = make_trades([
        {"side": "long", "signal_time": "2025-12-01 00:00:00", "entry_time": "2025-12-01 00:00:00",
         "exit_time": "2025-12-01 01:00:00", "entry": 100.0, "exit": 110.0, "stop": 95.0, "target": 110.0,
         "exit_reason": "target", "risk_%": 5.0, "ret_net": 0.10, "r_net": 2.0},
        {"side": "long", "signal_time": "2026-01-01 00:00:00", "entry_time": "2026-01-01 00:01:00",
         "exit_time": last_minute, "entry": 100.0, "exit": 100.0, "stop": 95.0, "target": 120.0,
         "exit_reason": "data_gap", "risk_%": 5.0, "ret_net": 0.0, "r_net": 0.0},
    ])
    summary = engine.summary()
    assert summary["trades"] == 1  # only the closed trade counts toward win rate
    assert summary["wins"] == 1
    assert summary["open_positions"] == 1
    # balance = 1000 * 1.10 (closed) * 1.10 (open, marked at 110 vs entry 100) = 1210
    assert summary["balance"] == 1210.0


def test_trade_records_exposes_closed_entries_and_exits_for_chart_markers() -> None:
    engine = PaperEngine(trade_log_path=Path("/tmp/unused_trades.csv"))
    engine.minutes = make_minutes("2026-01-01 00:10:00")
    last_minute = engine.minutes.index[-1]
    engine.trades = make_trades([
        {"side": "long", "signal_time": "2025-12-01 00:00:00", "entry_time": "2025-12-01 00:00:00",
         "exit_time": "2025-12-01 01:00:00", "entry": 100.0, "exit": 110.0, "stop": 95.0, "target": 110.0,
         "exit_reason": "target", "risk_%": 5.0, "ret_net": 0.10, "r_net": 2.0},
        {"side": "long", "signal_time": "2026-01-01 00:00:00", "entry_time": "2026-01-01 00:01:00",
         "exit_time": last_minute, "entry": 100.0, "exit": 100.0, "stop": 95.0, "target": 120.0,
         "exit_reason": "data_gap", "risk_%": 5.0, "ret_net": 0.0, "r_net": 0.0},
    ])
    records = engine.trade_records()
    assert len(records) == 1  # the still-open trade is excluded, matching closed_trades()
    record = records[0]
    assert record["side"] == "long" and record["entry"] == 100.0 and record["exit"] == 110.0
    assert record["entry_time"] == "2025-12-01T00:00:00+00:00"
    assert record["pnl_pct"] == 10.0
    assert record["strategy_name"]


def test_trade_log_round_trips_and_deduplicates_by_signal_time(tmp_path) -> None:
    log_path = tmp_path / "trades.csv"
    engine = PaperEngine(trade_log_path=log_path)
    engine.minutes = make_minutes("2026-01-01 00:10:00")
    computed = make_trades([{
        "side": "long", "signal_time": "2025-12-01", "entry_time": "2025-12-01", "exit_time": "2025-12-01 01:00:00",
        "entry": 100.0, "exit": 110.0, "stop": 95.0, "target": 110.0, "exit_reason": "target",
        "risk_%": 5.0, "ret_net": 0.10, "r_net": 2.0,
    }])
    engine._persist_new_trades(computed)
    assert log_path.exists()
    assert len(engine.trades) == 1

    reloaded = PaperEngine(trade_log_path=log_path)
    reloaded._load_trade_log()
    assert len(reloaded.trades) == 1

    # re-persisting the same computed trade must not duplicate it in the log
    engine._persist_new_trades(computed)
    assert len(pd.read_csv(log_path)) == 1
