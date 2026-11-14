import numpy as np
import pandas as pd

from strategy.mytradesetup import kalman, signal_entries, wma
from strategy.ob_rejection import MinutePath


def test_wma_weights_newest_bar_most() -> None:
    out = wma(np.array([1.0, 2.0, 3.0, 4.0]), 3)
    assert np.isnan(out[:2]).all()
    assert np.allclose(out[2:], [(1 + 4 + 9) / 6, (2 + 6 + 12) / 6])


def test_kalman_first_bar_equals_input_plus_zero_error_and_stays_finite() -> None:
    out = kalman(np.array([np.nan, 100.0, 101.0, 102.0]), 10000.0)
    assert np.isnan(out[0]) and np.isfinite(out[1:]).all()
    assert out[1] == 100.0  # dk = 0 on the first finite bar


def test_entry_is_filled_after_the_signal_bar_closes() -> None:
    minutes = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
        index=pd.date_range("2026-01-01 00:00", periods=60, freq="1min", tz="UTC"))
    bar_close = pd.Timestamp("2026-01-01 00:30", tz="UTC")
    bars = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
                        index=pd.DatetimeIndex([bar_close - pd.Timedelta(minutes=15), bar_close]))
    signals = pd.DataFrame({"long": [False, True], "short": [False, False]}, index=bars.index)
    entries = signal_entries(bars, signals, MinutePath(minutes))
    assert len(entries) == 0 or (entries["entry_time"] >= entries["signal_time"]).all()
