import pandas as pd

from strategy.luxalgo_internal_ob import OrderBlock
from strategy.ob_touch_15m import (
    EntryConfig,
    TrailConfig,
    build_entries,
    near_touch_candidates,
    walk_trailing_exit,
)
from strategy.ob_rejection import MinutePath


def bars(rows: list[tuple[float, float, float, float]], start="2026-01-01", freq="15min") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    frame["volume"] = 1.0
    return frame


def minutes(rows: list[tuple[float, float, float, float]], start="2026-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    frame["volume"] = 1.0
    return frame


def test_touch_only_fires_when_price_enters_the_zone_not_before() -> None:
    # bullish block: zone [95, 100]; price drifts down but stops just above the zone, then dips in
    bar_frame = bars([
        (110, 111, 109, 110),
        (109, 110, 101, 102),  # low 101, still above top=100: no touch yet
        (102, 103, 94, 95),    # low 94 <= top=100: touch
        (95, 96, 93, 94),
    ])
    block = OrderBlock(block_id=1, created_at=bar_frame.index[0], top=100.0, bottom=95.0, bias=1,
                        expires_at=bar_frame.index[-1] + pd.Timedelta(minutes=15))
    touch_cfg = EntryConfig(near_mode="touch")
    events = near_touch_candidates(bar_frame, [block], touch_cfg)
    assert len(events) == 1
    assert events.iloc[0]["signal_time"] == bar_frame.index[2]
    assert events.iloc[0]["touch_type"] == "touch"


def test_near_mode_fires_earlier_than_touch_on_the_same_data() -> None:
    bar_frame = bars([
        (110, 111, 109, 110),
        (109, 110, 101, 102),  # low 101: within 5 of top=100 -> near-touch with a wide buffer
        (102, 103, 94, 95),
        (95, 96, 93, 94),
    ])
    block = OrderBlock(block_id=1, created_at=bar_frame.index[0], top=100.0, bottom=95.0, bias=1,
                        expires_at=bar_frame.index[-1] + pd.Timedelta(minutes=15))
    near_cfg = EntryConfig(near_mode="pct", near_pct=0.05)  # 5% of 100 = 5, buffer covers low=101
    events = near_touch_candidates(bar_frame, [block], near_cfg)
    assert len(events) == 1
    assert events.iloc[0]["signal_time"] == bar_frame.index[1]
    assert events.iloc[0]["touch_type"] == "near"


def test_bullish_block_only_produces_a_long_side_and_bearish_only_short() -> None:
    bar_frame = bars([(100, 101, 99, 100)] * 5)
    bull = OrderBlock(1, bar_frame.index[0], top=100.0, bottom=95.0, bias=1, expires_at=bar_frame.index[-1])
    bear = OrderBlock(2, bar_frame.index[0], top=105.0, bottom=100.0, bias=-1, expires_at=bar_frame.index[-1])
    events = near_touch_candidates(bar_frame, [bull, bear], EntryConfig(near_mode="touch"))
    sides = dict(zip(events["block_id"], events["side"]))
    assert sides[1] == 1
    assert sides[2] == -1


def test_build_entries_resolves_to_the_exact_minute_and_fill_within_the_15m_bar() -> None:
    # entry bar spans minutes [15, 30); price only dips to touch at minute 22
    rows = [(100, 100, 100, 100)] * 15 + [(100, 100.5, 94.0, 99)] * 15
    minute_frame = minutes(rows)
    path = MinutePath(minute_frame)
    candidate = pd.DataFrame([{
        "signal_time": minute_frame.index[29], "bar_start": minute_frame.index[15],
        "side": 1, "block_id": 1, "block_created_at": minute_frame.index[0],
        "top": 95.0, "bottom": 90.0, "trigger_level": 95.0, "touch_type": "touch",
        "near_buffer": 0.0, "distance_pct": 0.0, "atr": 1.0, "candle_low": 94.0, "candle_high": 100.5,
    }])
    entries = build_entries(candidate, path, entry_minutes=15)
    assert len(entries) == 1
    assert entries.iloc[0]["entry"] == 95.0
    assert entries.iloc[0]["entry_time"] >= minute_frame.index[15]
    assert entries.iloc[0]["entry_time"] <= minute_frame.index[29]


def test_trailing_stop_never_moves_against_the_position_and_ratchets_up_for_a_long() -> None:
    rows = [
        (100, 100, 100, 100),   # entry minute
        (100, 103, 100, 103),   # price rallies; once >= activate, trail should start following
        (103, 108, 103, 108),
        (108, 107, 95, 96),     # sharp drop back down: trailing stop (set behind the prior high) should catch it
    ]
    path = MinutePath(minutes(rows))
    trail = TrailConfig(stop_buffer_atr=0.0, trail_activate_r=1.0, trail_atr_mult=1.0, max_hours=1)
    # entry 100, initial stop 98 (risk=2), atr=1 -> trail activates once price is 2 points ahead (102)
    exit_i, fill, reason, final_stop = walk_trailing_exit(path, 0, side=1, entry=100.0, stop0=98.0, atr=1.0, trail=trail)
    assert reason in ("trail_stop", "stop")
    assert final_stop >= 98.0  # the stop only ever moved up for a long, never back down toward entry
    assert fill <= 108.0  # exited below the peak, consistent with trailing behind the high, not above it


def test_trailing_stop_exits_at_hard_stop_before_activation() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 97, 98),  # drops straight through the initial stop before ever being 1R ahead
    ]
    path = MinutePath(minutes(rows))
    trail = TrailConfig(stop_buffer_atr=0.0, trail_activate_r=1.0, trail_atr_mult=1.0, max_hours=1)
    exit_i, fill, reason, final_stop = walk_trailing_exit(path, 0, side=1, entry=100.0, stop0=98.0, atr=1.0, trail=trail)
    assert reason == "stop"
    assert fill == 98.0
    assert final_stop == 98.0  # never activated, so the stop never moved from its initial level
