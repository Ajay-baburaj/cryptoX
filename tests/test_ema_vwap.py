import numpy as np
import pandas as pd

from strategy.ema_vwap import (
    EmaVwapConfig,
    filter_mask,
    prepare_bars,
    session_vwap,
    signals,
)


def minute_bars(rows: list[tuple[float, float, float, float, float]], start: str = "2026-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)


def test_config_round_trips_through_yaml(tmp_path) -> None:
    path = tmp_path / "ema_vwap.yaml"
    path.write_text(
        "strategy:\n  symbol: BTCUSD\n  timeframe_minutes: 15\n  fast_ema: 9\n  slow_ema: 20\n"
        "  session_reset_utc_hour: 0\n  trigger: cross\n  stop: atr\n  stop_atr: 1.5\n"
        "  swing_lookback: 10\n  min_stop_pct: 0.002\n  target_r: 1.5\n  exit_on: none\n"
        "  flat_at_session_end: true\n  max_hours: 24\n  skip_open_minutes: 0\n  min_adx: 0\n"
        "  htf_filter: none\n  min_ema_gap_atr: 0\n  sides: both\n  fee_per_side: 0.00059\n"
        "  risk_per_trade_pct: 1.0\n  max_leverage: 10.0\n"
        "data:\n  minute_parquet: x\n  train_test_split: '2026-06-01'\n"
    )
    config = EmaVwapConfig.load(path)
    assert config.timeframe_minutes == 15
    assert config.trigger == "cross"


def test_session_vwap_resets_daily_at_configured_hour() -> None:
    # Two days of flat, identical price/volume bars: VWAP should equal price (no drift) and
    # the second day's first bar should not be weighted by the first day's bars.
    rows = [(100, 100, 100, 100, 1.0)] * 1440 + [(200, 200, 200, 200, 1.0)] * 5
    bars = minute_bars(rows)
    vwap, session = session_vwap(bars, reset_utc_hour=0)
    assert vwap.iloc[-1] == 200  # day 2 VWAP is not dragged down by day 1's price
    assert session.iloc[0] != session.iloc[-1]


def test_cross_trigger_fires_only_when_vwap_already_agrees() -> None:
    # Build a 5m-aggregatable series: price crosses above a flat VWAP level, and the EMA9/20
    # cross happens while price is already above VWAP, so a long should fire.
    n = 200
    rng = np.arange(n)
    base = 100 + np.where(rng < 100, 0.0, (rng - 100) * 0.5)  # flat then trending up
    rows = [(p, p + 0.1, p - 0.1, p, 10.0) for p in base]
    minutes = minute_bars(rows)
    config = EmaVwapConfig(timeframe_minutes=5, fast_ema=3, slow_ema=6, trigger="cross")
    bars = prepare_bars(minutes, config)
    events = signals(bars, config)
    assert not events.empty
    assert set(events["side"].unique()) <= {1, -1}
    # every fired long event must have had price above VWAP and EMA9 above EMA20 at signal time
    for row in events.itertuples(index=False):
        idx = bars.index.get_loc(row.signal_time)
        bar = bars.iloc[idx]
        side_from_vwap = 1 if bar["close"] > bar["vwap"] else -1
        side_from_ema = 1 if bar["ema_fast"] > bar["ema_slow"] else -1
        assert side_from_vwap == side_from_ema == row.side


def test_filter_mask_sides_and_skip_open() -> None:
    events = pd.DataFrame({
        "side": [1, -1, 1, -1],
        "minutes_in_session": [10, 70, 200, 5],
        "adx": [30, 30, 30, 30],
        "ema_gap_atr": [1.0, 1.0, 1.0, 1.0],
        "h1_ema50_dir": [1, 1, 1, 1],
        "h4_ema50_dir": [1, 1, 1, 1],
    })
    long_only = filter_mask(events, EmaVwapConfig(sides="long"))
    assert list(long_only) == [True, False, True, False]
    skip_60 = filter_mask(events, EmaVwapConfig(skip_open_minutes=60))
    assert list(skip_60) == [False, True, True, False]
