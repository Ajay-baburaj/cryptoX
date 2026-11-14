import numpy as np
import pandas as pd

from strategy.ob15_research import ExitSpec, barrier, walk_exit_variant
from strategy.ob_rejection import MinutePath
from strategy.ob_touch_15m import TrailConfig, walk_trailing_exit


def make_path(highs, lows, opens=None) -> MinutePath:
    n = len(highs)
    index = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    opens = opens if opens is not None else [(h + l) / 2 for h, l in zip(highs, lows)]
    frame = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": opens, "volume": 1.0}, index=index)
    return MinutePath(frame)


def test_trail_only_walker_matches_production_walk() -> None:
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 0.3, 400))
    path = make_path(close + 0.2, close - 0.2, list(close))
    for side in (1, -1):
        a = walk_trailing_exit(path, 5, side, float(close[5]), float(close[5]) - side * 2.0, 0.5, TrailConfig())
        b = walk_exit_variant(path, 5, side, float(close[5]), float(close[5]) - side * 2.0, 0.5, ExitSpec())
        assert a[0] == b[0] and abs(a[1] - b[1]) < 1e-9 and a[2] == b[2]


def test_fixed_target_fills_at_target_and_stop_wins_a_same_minute_tie() -> None:
    path = make_path([100, 101, 103, 106], [100, 99.5, 100, 101])
    exit_i, fill, reason, _, _ = walk_exit_variant(path, 0, 1, 100.0, 98.0, 1.0, ExitSpec(activate_r=None, target_r=1.0))
    assert (exit_i, fill, reason) == (2, 102.0, "target")  # +1R = 102, first reached on minute 2
    tie = make_path([100, 103], [100, 97])  # minute 1 touches both +1R and the stop
    _, fill, reason, _, _ = walk_exit_variant(tie, 0, 1, 100.0, 98.0, 1.0, ExitSpec(activate_r=None, target_r=1.0))
    assert reason == "stop"


def test_breakeven_moves_stop_to_entry_after_the_trigger() -> None:
    path = make_path([100, 103, 101, 100], [100, 100.5, 99.9, 99.0])
    exit_i, fill, reason, _, final_stop = walk_exit_variant(path, 0, 1, 100.0, 98.0, 1.0,
                                                            ExitSpec(activate_r=None, be_r=1.0))
    assert reason == "trail_stop" and final_stop == 100.0 and exit_i == 2


def test_barrier_is_stop_first_on_a_tie_and_reports_excursions_in_r() -> None:
    path = make_path([100, 101, 103, 104], [100, 99.5, 99.0, 99.0])
    out = barrier(path, 0, 1, 100.0, 2.0, horizon_min=4, ks=(1.0,), mfe_horizons=(4,))
    assert out["p1.0"] == 1.0 and out["mfe4"] == 2.0 and abs(out["mae4"] - 0.5) < 1e-9
    tie = make_path([100, 103], [100, 97])
    assert barrier(tie, 0, 1, 100.0, 2.0, horizon_min=2, ks=(1.0,), mfe_horizons=(2,))["p1.0"] == 0.0
