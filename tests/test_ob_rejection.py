import pandas as pd

from strategy.ob_rejection import MinutePath, clean_minutes, walk_exit


def minutes(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq="1min", tz="UTC")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    frame["volume"] = 1.0
    return frame


def test_minute_touching_stop_and_target_counts_as_stop() -> None:
    path = MinutePath(minutes([(100, 100.5, 99.5, 100), (100, 102, 98, 100)]))
    exit_i, fill, reason = walk_exit(path, 0, 1, 100.0, 99.0, 101.0, 60)
    assert (exit_i, fill, reason) == (1, 99.0, "stop")


def test_target_fill_and_gap_through_stop_fills_at_open() -> None:
    path = MinutePath(minutes([(100, 100.5, 99.5, 100), (100, 101.5, 100, 101)]))
    assert walk_exit(path, 0, 1, 100.0, 99.0, 101.0, 60)[1:] == (101.0, "target")
    gapped = MinutePath(minutes([(100, 100.5, 99.5, 100), (97, 97.5, 96, 97)]))
    assert walk_exit(gapped, 0, 1, 100.0, 99.0, 101.0, 60)[1:] == (97.0, "stop")


def test_clean_minutes_clips_lone_print_but_keeps_real_move() -> None:
    rows = [(100, 100.2, 99.8, 100)] * 40
    rows[10] = (100, 170, 99.8, 100)  # single bad print, body unchanged
    clean = clean_minutes(minutes(rows))
    assert clean["high"].iloc[10] == 100
    crash = [(100, 100.2, 99.8, 100)] * 20 + [(90, 90.2, 89.8, 90)] * 20
    assert clean_minutes(minutes(crash))["low"].min() == 89.8
