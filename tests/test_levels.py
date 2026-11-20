import numpy as np
import pandas as pd

from btc_agents.features import indicators
from btc_agents.levels import zone_levels


def bars(prices, start="2026-01-05", freq="1h"):
    index = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=len(prices), freq=freq)
    values = pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices,
                           "volume": 1.0}, index=index)
    # Give every pivot a touch of range so ATR is nonzero and tolerances are meaningful.
    values["high"] = values.high + 0.5
    values["low"] = values.low - 0.5
    return indicators(values, "1h")


WARMUP = 25  # enough closed bars for Wilder ATR(14) to be available before the pivot


def test_pivot_builds_a_zone_that_price_later_approaches():
    prices = [100] * WARMUP + [130] + [100] * 30
    frame = bars(prices)
    row = frame.iloc[-1]
    assert row.zone_resistance_strength > 0
    assert row.zone_resistance_low <= 130.5 <= row.zone_resistance_high


def test_zone_strength_rewards_repeated_touches():
    prices = [100] * WARMUP + [130] + [100] * 10 + [129.8] + [100] * 30
    frame = bars(prices)
    single_touch = [100] * WARMUP + [130] + [100] * 41
    once = bars(single_touch)
    assert frame.iloc[-1].zone_resistance_strength > once.iloc[-1].zone_resistance_strength


def test_future_spike_changes_nothing_before_it():
    prices = [100] * WARMUP + [130] + [100] * 40
    frame = bars(prices)
    spiked = list(prices)
    spiked[-1] = 500
    frame2 = bars(spiked)
    cut = len(frame) - 5
    pd.testing.assert_series_equal(
        frame.iloc[:cut].zone_resistance_strength, frame2.iloc[:cut].zone_resistance_strength)
    pd.testing.assert_series_equal(
        frame.iloc[:cut].zone_resistance_low, frame2.iloc[:cut].zone_resistance_low)


def test_pivot_needs_right_bars_to_confirm_before_it_can_be_used():
    prices = [100] * WARMUP + [130] + [100] * 10
    frame = zone_levels(bars(prices), "1h")
    pivot_idx = WARMUP
    # Not yet confirmed: fewer than `right` closed bars after the pivot.
    assert np.isnan(frame.zone_resistance_low.iloc[pivot_idx])
    assert np.isnan(frame.zone_resistance_low.iloc[pivot_idx + 1])
    # Confirmed `right` bars later (right=3 for 1h).
    assert frame.zone_resistance_low.iloc[pivot_idx + 3] == 130.5
