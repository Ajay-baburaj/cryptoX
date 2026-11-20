"""Construct UTC, close-labelled features from one-minute opens."""
import numpy as np
import pandas as pd

from .levels import zone_levels

OHLCV = ["open", "high", "low", "close", "volume"]
TIMEFRAMES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


def utc_index(values):
    if pd.api.types.is_numeric_dtype(values):
        raise ValueError("Use ISO UTC timestamps, or convert epoch values explicitly before importing")
    index = pd.DatetimeIndex(pd.to_datetime(values, utc=True, format="mixed"))
    if index.hasnans:
        raise ValueError("Missing timestamps")
    return index


def validate_minutes(frame):
    frame = frame.copy()
    frame.index = utc_index(frame.pop("time") if "time" in frame else frame.index)
    if frame.index.has_duplicates or (frame.index != frame.index.floor("min")).any():
        raise ValueError("Minute opens must be unique and aligned to UTC minutes")
    columns = OHLCV + (["taker_buy_volume"] if "taker_buy_volume" in frame else [])
    frame = frame[columns].apply(pd.to_numeric, errors="raise").sort_index()
    if frame.empty:
        raise ValueError("No minute bars")
    prices = frame[OHLCV[:4]]
    if (not np.isfinite(frame[OHLCV].to_numpy()).all() or (prices <= 0).any().any()
            or (frame.low > prices.min(axis=1)).any() or (frame.high < prices.max(axis=1)).any()
            or (frame.volume < 0).any()):
        raise ValueError("Invalid OHLCV values")
    if "taker_buy_volume" in frame:
        buy = frame.taker_buy_volume.dropna()
        if ((buy < 0) | (buy > frame.volume.loc[buy.index] + 1e-9)).any():
            raise ValueError("Invalid taker buy volume")
    return frame.rename_axis("time")


def complete_bars(minutes, period):
    size = TIMEFRAMES[period]
    groups = minutes.resample(f"{size}min", origin="epoch",
                              closed="left", label="right")
    bars = groups.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    if "taker_buy_volume" in minutes:
        bars["taker_buy_volume"] = groups.taker_buy_volume.sum(min_count=size)
    return bars.loc[groups.size().eq(size)]


def wilder(series, length=14):
    values = series.dropna()
    if len(values) < length:
        return pd.Series(np.nan, index=series.index)
    seeded = values.iloc[length - 1:].copy()
    seeded.iloc[0] = values.iloc[:length].mean()
    return seeded.ewm(alpha=1 / length, adjust=False).mean().reindex(series.index)


def indicators(bars, period):
    bars = bars.copy()
    close, high, low, volume = bars.close, bars.high, bars.low, bars.volume
    previous = close.shift()
    true_range = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = wilder(true_range)
    up, down = high.diff(), -low.diff()
    plus = 100 * wilder(up.where((up > down) & (up > 0), 0)) / atr.where(atr > 0)
    minus = 100 * wilder(down.where((down > up) & (down > 0), 0)) / atr.where(atr > 0)
    di_sum = plus + minus
    bars["atr"], bars["plus_di"], bars["minus_di"] = atr, plus, minus
    bars["adx"] = wilder((100 * (plus - minus).abs() / di_sum.where(di_sum > 0)).mask(di_sum.eq(0), 0))

    delta = close.diff()
    gain, loss = wilder(delta.clip(lower=0)), wilder(-delta.clip(upper=0))
    bars["rsi"] = (100 - 100 / (1 + gain / loss)).mask(gain.eq(0) & loss.eq(0), 50)
    for length in (20, 50, 200):
        bars[f"ema{length}"] = close.ewm(span=length, adjust=False, min_periods=length).mean()
    macd = (close.ewm(span=12, adjust=False, min_periods=12).mean()
            - close.ewm(span=26, adjust=False, min_periods=26).mean())
    bars["macd_hist"] = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()
    bars["bandwidth"] = 4 * close.rolling(20).std(ddof=0) / close.rolling(20).mean()
    bars["rv24h"] = np.log(close).diff().rolling(1440 // TIMEFRAMES[period]).std() if TIMEFRAMES[period] < 1440 else np.nan
    bars["rvol"] = volume / volume.shift().rolling(20).mean().replace(0, np.nan)
    bars["range_high"], bars["range_low"] = high.shift().rolling(20).max(), low.shift().rolling(20).min()
    bars["wide_high"], bars["wide_low"] = high.shift().rolling(60).max(), low.shift().rolling(60).min()
    bars["momentum"] = close.pct_change({"4h": 6}.get(period, 3), fill_method=None)
    bars["obv"] = (np.sign(delta).fillna(0) * volume).cumsum()
    if TIMEFRAMES[period] < 1440:
        day = (bars.index - pd.Timedelta(nanoseconds=1)).normalize()
        typical = (high + low + close) / 3
        vwap = (typical * volume).groupby(day).cumsum() / volume.groupby(day).cumsum().replace(0, np.nan)
        session_started = pd.Series(bars.index - pd.Timedelta(minutes=TIMEFRAMES[period]) == day,
                                    index=bars.index).groupby(day).cummax()
        bars["vwap"] = vwap.where(session_started)
    if "taker_buy_volume" in bars:
        signed = 2 * bars.taker_buy_volume - volume
        bars["taker_imbalance"] = signed / volume.replace(0, np.nan)
        bars["cvd"] = signed.groupby(signed.isna().cumsum()).cumsum()
    bars["atr_pct"] = 100 * atr / close
    reference = bars.atr_pct.shift().rolling(100)
    lower, upper = reference.quantile(.25), reference.quantile(.75)
    bars["volatility"] = np.select(
        [lower.isna(), bars.atr_pct < lower, bars.atr_pct > upper],
        ["unknown", "low", "high"], default="normal")
    bars["trend"] = np.select(
        [bars.adx.isna(), bars.adx < 20, plus > minus, minus > plus],
        ["unknown", "range", "up", "down"], default="mixed")
    if period == "4h":
        raw = np.sign(close - bars.ema50)
        confirmed = raw.where(raw.eq(raw.shift()) & raw.ne(0))
        bars["bias"] = confirmed.ffill()
    if period in ("4h", "1h"):
        bars = bars.join(zone_levels(bars, period))
    return bars


def features(minutes):
    snapshots = {}
    for period, length in TIMEFRAMES.items():
        bars = complete_bars(minutes, period)
        if bars.empty:
            snapshots[period] = bars
            continue
        segment = bars.index.to_series().diff().ne(pd.Timedelta(minutes=length)).cumsum()
        snapshots[period] = pd.concat([indicators(run, period) for _, run in bars.groupby(segment)])

    trigger = snapshots["5m"]
    if trigger.empty:
        raise ValueError("No complete 5-minute bars")
    result = trigger.add_prefix("m5_")
    for period, prefix in (("15m", "m15"), ("1h", "h1"), ("4h", "h4")):
        frame = snapshots[period]
        aligned = pd.merge_asof(
            pd.DataFrame(index=trigger.index),
            frame.assign(source_close=frame.index).add_prefix(f"{prefix}_"),
            left_index=True, right_index=True, direction="backward",
            tolerance=pd.Timedelta(minutes=TIMEFRAMES[period]) - pd.Timedelta(nanoseconds=1),
        )
        result = result.join(aligned)
    return result
