import numpy as np
import pandas as pd
import pytest

from research.ob_timeframes import Zone
from strategy.ob_mitigation_1h import Config, OB1hStrategy, NS_MIN

T0 = pd.Timestamp("2026-01-01 00:00", tz="UTC")


def hour_bars(n=10, price=100.0, atr=1.0):
    idx = pd.date_range(T0, periods=n, freq="1h")  # close times
    bars = pd.DataFrame({"open": price, "high": price + 0.5, "low": price - 0.5, "close": price,
                         "volume": 1.0, "segment": 0, "atr": atr}, index=idx)
    return bars


def build(side, top, bottom, bars, **cfg):
    s = OB1hStrategy(Config(fee_per_side=0.0, slippage_per_side=0.0, risk_pct=1.0, start_balance=1000.0, **cfg))
    s._set_arrays(bars)
    s.zones = [Zone(0, T0, top, bottom, side, 0, 0)]
    s.visible = [(0,)] * len(bars)
    return s


def feed(s, start, candles):
    """candles: list of (o, h, l, c) one per minute starting at ``start``; returns all events."""
    events = []
    ns = start.value
    for k, (o, h, l, c) in enumerate(candles):
        events += s.on_minute(ns + k * NS_MIN, o, h, l, c)
    return events


def test_bearish_block_revisit_shorts_with_stop_above_block():
    s = build(-1, top=110.0, bottom=108.0, bars=hour_bars(), stop_buffer_atr=0.25)
    start = T0 + pd.Timedelta(minutes=5)
    ev = feed(s, start, [(100, 101, 99, 100),            # outside, below the block
                         (100, 108.5, 100, 108),         # reaches the lower edge: signal
                         (108, 108.2, 107, 107.5)])      # next open fills the short
    assert [e["type"] for e in ev] == ["signal", "entry"]
    pos = s.position
    assert pos["side"] == "short" and pos["entry"] == 108
    assert pos["initial_stop"] == pytest.approx(110.0 + 0.25)  # above the block top + buffer
    assert pos["risk_usd"] == pytest.approx(10.0)  # 1% of 1000


def test_bullish_block_revisit_longs_with_stop_below_block():
    s = build(1, top=92.0, bottom=90.0, bars=hour_bars(), stop_buffer_atr=0.25)
    feed(s, T0 + pd.Timedelta(minutes=5), [(100, 101, 99, 100), (100, 100, 91.5, 92), (92, 93, 91, 92.5)])
    pos = s.position
    assert pos["side"] == "long" and pos["entry"] == 92
    assert pos["initial_stop"] == pytest.approx(90.0 - 0.25)


def test_block_is_traded_only_once_and_first_touch_consumes_it():
    s = build(-1, 110.0, 108.0, hour_bars())
    start = T0 + pd.Timedelta(minutes=5)
    feed(s, start, [(100, 101, 99, 100), (100, 108.5, 100, 108), (108, 109, 107, 108),
                    (108, 112.5, 107, 111)])  # stop (110.25) hit
    assert s.position is None and len(s.trades) == 1 and s.trades[0]["exit_reason"] == "initial_stop"
    ev = feed(s, start + pd.Timedelta(minutes=4), [(111, 111, 99, 100), (100, 109, 100, 108), (108, 108, 100, 101)])
    assert ev == [] and s.position is None  # the block was already consumed


def test_touch_from_inside_or_after_gap_is_consumed_without_a_trade():
    s = build(-1, 110.0, 108.0, hour_bars())
    ev = feed(s, T0 + pd.Timedelta(minutes=5), [(109, 109.5, 108.5, 109), (109, 109, 100, 100)])
    assert ev == [] and s.position is None and len(s.consumed) == 1


def test_stop_never_moves_before_activation_then_trails_on_closed_hour_candles_only_tightening():
    bars = hour_bars(n=8, price=100.0, atr=1.0)
    s = build(-1, 110.0, 108.0, bars, stop_buffer_atr=0.25, trail_lookback=2, trail_buffer_atr=0.0, trail_activate_r=1.0)
    start = T0 + pd.Timedelta(hours=2, minutes=5)
    feed(s, start, [(100, 101, 99, 100), (100, 108.5, 100, 108), (108, 108, 107, 107)])
    pos = s.position
    entry, stop0 = pos["entry"], pos["initial_stop"]
    risk = stop0 - entry  # 2.25
    # Hour 3 is the entry candle (opened before the fill): even 1.5R in profit, it never moves the stop.
    bars.loc[T0 + pd.Timedelta(hours=3), ["high", "close", "low"]] = [entry - 0.1, entry - risk * 1.5, entry - risk * 1.6]
    s._set_arrays(bars)
    t3 = T0 + pd.Timedelta(hours=3)
    s.prev_ts, s.prev_close = t3.value - NS_MIN, 100.0
    assert s.on_minute(t3.value, 105, 105, 104, 104.5) == []
    assert s.position["stop"] == stop0
    # Hour 4 is the first full candle after entry and closes 1R in profit: trail to the highest high of the last 2 bars.
    bars.loc[T0 + pd.Timedelta(hours=4), ["high", "close", "low"]] = [entry - 0.2, entry - risk * 1.5, entry - risk * 1.6]
    s._set_arrays(bars)
    t4 = T0 + pd.Timedelta(hours=4)
    s.prev_ts, s.prev_close = t4.value - NS_MIN, 100.0
    ev = s.on_minute(t4.value, 105, 105, 104, 104.5)
    assert [e["type"] for e in ev] == ["trail"]
    assert s.position["stop"] < stop0 and s.position["stop"] == pytest.approx(max(bars.high.iloc[3:5]))
    tightened = s.position["stop"]
    # Next candle is back below 1R: nothing loosens the stop.
    bars.loc[T0 + pd.Timedelta(hours=5), ["high", "close"]] = [tightened + 5, entry]
    s._set_arrays(bars)
    s.on_minute((T0 + pd.Timedelta(hours=5)).value, 104, 104, 103, 103)
    assert s.position["stop"] <= tightened


def test_trailing_stop_exit_reports_reason_pnl_and_fees():
    bars = hour_bars(n=8)
    s = OB1hStrategy(Config(fee_per_side=0.001, slippage_per_side=0.0, risk_pct=1.0, start_balance=1000.0,
                             trail_activate_r=0, trail_lookback=1, trail_buffer_atr=0.0))
    s._set_arrays(bars)
    s.zones = [Zone(0, T0, 110.0, 108.0, -1, 0, 0)]
    s.visible = [(0,)] * len(bars)
    start = T0 + pd.Timedelta(hours=1, minutes=5)
    feed(s, start, [(100, 101, 99, 100), (100, 108.5, 100, 108), (108, 108, 107, 107)])
    assert s.position is not None
    # The 2h bar is the entry candle and is skipped. The 3h bar closes lower; the short trails down
    # to that bar's high and is then stopped out.
    bars.loc[T0 + pd.Timedelta(hours=2), ["high", "low", "close"]] = [104.0, 100.0, 101.0]
    bars.loc[T0 + pd.Timedelta(hours=3), ["high", "low", "close"]] = [104.0, 100.0, 101.0]
    s._set_arrays(bars)
    s.on_minute((T0 + pd.Timedelta(hours=2)).value, 107, 107, 106, 106)
    assert s.position["stop"] == s.position["initial_stop"]
    t2 = T0 + pd.Timedelta(hours=3)
    s.prev_ts, s.prev_close = t2.value - NS_MIN, 107.0
    s.on_minute(t2.value, 103, 103.5, 102, 103)
    assert s.position["stop"] == pytest.approx(104.0)
    s.on_minute(t2.value + NS_MIN, 103, 104.5, 103, 104)
    trade = s.trades[0]
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit"] == pytest.approx(104.0)
    qty = trade["qty"]
    assert trade["pnl"] == pytest.approx(qty * (108 - 104.0) - qty * 108 * 0.001 - qty * 104.0 * 0.001)
    assert s.balance == pytest.approx(1000 + trade["pnl"])


def test_gap_through_stop_fills_at_worse_open():
    s = build(-1, 110.0, 108.0, hour_bars())
    feed(s, T0 + pd.Timedelta(minutes=5), [(100, 101, 99, 100), (100, 108.5, 100, 108), (108, 108, 107, 107),
                                           (115, 116, 114, 115)])
    assert s.trades[0]["exit"] == pytest.approx(115)  # not the 110.25 stop


def test_entry_skipped_when_fill_is_beyond_the_stop():
    s = build(-1, 110.0, 108.0, hour_bars())
    ev = feed(s, T0 + pd.Timedelta(minutes=5), [(100, 101, 99, 100), (100, 111.5, 100, 111), (111, 112, 110, 111)])
    assert [e["type"] for e in ev] == ["signal", "skipped"] and s.position is None


def test_state_round_trip_and_baseline_consumes_already_revisited_blocks():
    bars = hour_bars()
    bars.loc[T0 + pd.Timedelta(hours=3), "high"] = 109.0  # a 1h bar already traded into the bear block
    s = build(-1, 110.0, 108.0, bars)
    s.baseline((T0 + pd.Timedelta(hours=9)).value)
    assert len(s.consumed) == 1
    t = OB1hStrategy(s.cfg)
    t.from_state(s.to_state())
    assert t.consumed == s.consumed and t.balance == s.balance


def test_15m_blocks_trail_on_15m_candles_and_skip_the_entry_candle():
    idx = pd.date_range(T0, periods=12, freq="15min")  # close times
    bars = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0,
                         "segment": 0, "atr": 1.0}, index=idx)
    s = build(-1, 110.0, 108.0, bars, timeframe_minutes=15, trail_activate_r=0, trail_lookback=1, trail_buffer_atr=0.0)
    start = T0 + pd.Timedelta(minutes=17)
    feed(s, start, [(100, 101, 99, 100), (100, 108.5, 100, 108), (108, 108, 107, 107)])  # fill at 00:19
    assert s.position is not None and s.tf_ns == 15 * NS_MIN
    t30, t45 = T0 + pd.Timedelta(minutes=30), T0 + pd.Timedelta(minutes=45)
    bars.loc[t30, "high"] = 104.0  # the 00:15-00:30 candle contains the entry: never used
    bars.loc[t45, "high"] = 103.0  # the first full 15m candle after entry
    s._set_arrays(bars)
    s.prev_ts, s.prev_close = t30.value - NS_MIN, 103.0
    s.on_minute(t30.value, 103, 103, 102, 102.5)
    assert s.position["stop"] == s.position["initial_stop"]
    s.prev_ts = t45.value - NS_MIN
    ev = s.on_minute(t45.value, 102, 102, 101, 101.5)
    assert [e["type"] for e in ev] == ["trail"] and s.position["stop"] == pytest.approx(103.0)


def test_make_bars_gap_segments_follow_the_timeframe():
    from strategy.ob_mitigation_1h import make_bars
    idx = pd.DatetimeIndex([T0 + pd.Timedelta(minutes=m) for m in (5, 10, 15, 25, 30)])
    raw = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    assert make_bars(raw, 5)["segment"].tolist() == [0, 0, 0, 1, 1]
