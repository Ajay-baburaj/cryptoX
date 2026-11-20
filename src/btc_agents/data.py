"""Read local market archives and collect public market data without credentials."""
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from zipfile import ZipFile

import numpy as np
import pandas as pd
import requests

from .features import OHLCV, utc_index, validate_minutes

DELTA = "https://api.india.delta.exchange/v2"
BINANCE = "https://fapi.binance.com"
BINANCE_COLUMNS = [
    "open_time", *OHLCV, "close_time", "quote_volume", "trade_count", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]


def minute_file(path):
    path = Path(path)
    frame = pd.read_csv(path) if path.suffix == ".csv" else pd.read_parquet(path)
    return validate_minutes(frame)


def attach_trade_flow(minutes, archive):
    if "taker_buy_volume" not in archive:
        raise ValueError("Flow archive needs taker_buy_volume")
    archive = archive.reindex(minutes.index)
    # Require reconciliation of price and volume before transferring signed trades.
    matched = minutes[OHLCV].eq(archive[OHLCV]).all(axis=1)
    return minutes.assign(taker_buy_volume=archive.taker_buy_volume.where(matched))


def funding_file(path):
    if path is None:
        return None
    path = Path(path)
    frame = pd.read_csv(path) if path.suffix == ".csv" else pd.read_parquet(path)
    date = frame["time"] if "time" in frame else frame["settled_at"]
    rate = frame["rate"] if "rate" in frame else frame["last_funding_rate"]
    series = pd.Series(pd.to_numeric(rate, errors="raise").to_numpy(), index=utc_index(date), name="rate")
    if series.index.has_duplicates or not np.isfinite(series.to_numpy()).all() or (series.abs() >= 1).any():
        raise ValueError("Funding needs unique settlement timestamps and rates as decimal fractions")
    return series.sort_index()


def local_binance(directory):
    directory = Path(directory)
    files = sorted(directory.glob("BTCUSDT-1m-*.zip"))
    if not files:
        raise FileNotFoundError(f"No Binance BTCUSDT 1m ZIPs in {directory}")
    columns = ["open_time", *OHLCV, "taker_buy_volume"]
    frames = []
    for path in files:
        with ZipFile(path) as archive, archive.open(archive.namelist()[0]) as source:
            has_header = source.peek(1).startswith(b"open_time")
            frames.append(pd.read_csv(source, header=0 if has_header else None,
                                      names=BINANCE_COLUMNS, usecols=columns))
    repair = directory.parent / "gap_20261028_rest.json"
    if repair.is_file():
        rows = pd.DataFrame(json.loads(repair.read_text()), columns=BINANCE_COLUMNS)
        frames.append(rows[columns])
    frame = pd.concat(frames, ignore_index=True).drop_duplicates()
    frame["time"] = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
    return validate_minutes(frame)


def _combine_delta(parts):
    return pd.concat(parts).groupby(level=0).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), taker_buy_volume=("taker_buy_volume", "sum"),
    )


def local_delta(directory):
    files = sorted(Path(directory).glob("futures-trades-monthly-BTCUSD-*.csv.zip"))
    if not files:
        raise FileNotFoundError(f"No Delta BTCUSD trade ZIPs in {directory}")
    monthly = []
    for path in files:
        parts = []
        previous = None
        with ZipFile(path) as archive, archive.open(archive.namelist()[0]) as source:
            columns = ["product_symbol", "timestamp", "price", "size", "buyer_role"]
            for chunk in pd.read_csv(source, usecols=columns, chunksize=500_000):
                if chunk.empty:
                    continue
                stamps = utc_index(chunk.timestamp)
                if not stamps.is_monotonic_increasing or previous is not None and stamps[0] < previous:
                    raise ValueError(f"Out of order trade timestamps in {path}")
                if (not chunk.product_symbol.eq("BTCUSD").all()
                        or not chunk.buyer_role.isin(["maker", "taker"]).all()
                        or not np.isfinite(chunk[["price", "size"]]).all().all()
                        or (chunk[["price", "size"]] <= 0).any().any()):
                    raise ValueError(f"Invalid trade, size or buyer role in {path}")
                previous = stamps[-1]
                chunk["minute"] = stamps.floor("min")
                chunk["buy"] = chunk["size"].where(chunk.buyer_role.eq("taker"), 0)
                parts.append(chunk.groupby("minute").agg(open=("price", "first"), high=("price", "max"),
                             low=("price", "min"), close=("price", "last"), volume=("size", "sum"),
                             taker_buy_volume=("buy", "sum")))
        if parts:
            monthly.append(_combine_delta(parts))
    if not monthly:
        raise ValueError("No Delta trades")
    return validate_minutes(pd.concat(monthly))


def get_json(session, url, params=None):
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=15)
            response.raise_for_status()
            content = response.json()
            if isinstance(content, dict) and content.get("success") is False:
                raise ValueError(f"{url} returned {content.get('error')}")
            return content
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
        except requests.HTTPError as error:
            if attempt == 2 or error.response.status_code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = error.response.headers.get("Retry-After", "")
            if retry_after.isdecimal() and int(retry_after) > 30:
                raise
            if retry_after.isdecimal():
                time.sleep(int(retry_after))
        time.sleep(2 ** attempt)


def delta_history(symbol, resolution, start, end, bar_size):
    frames = []
    with requests.Session() as session:
        while start < end:
            stop = min(end, start + 1800 * bar_size)
            result = get_json(session, f"{DELTA}/history/candles",
                              {"symbol": symbol, "resolution": resolution, "start": int(start.timestamp()),
                               "end": int(stop.timestamp())})["result"]
            if result:
                frame = pd.DataFrame(result)
                frame["time"] = pd.to_datetime(frame.time, unit="s", utc=True)
                frames.append(frame.loc[frame.time.ge(start) & frame.time.lt(stop)])
            start = stop
            if start < end:
                time.sleep(.25)
    if not frames or not any(len(frame) for frame in frames):
        raise ValueError(f"No Delta candles returned for {symbol} in the requested interval")
    return pd.concat(frames)


def download_delta(start, end, output):
    start = start.ceil("min")
    end = min(end.floor("min"), pd.Timestamp.now(tz="UTC").floor("min"))
    minutes = validate_minutes(delta_history("BTCUSD", "1m", start, end, pd.Timedelta(minutes=1)))
    output = Path(output)
    if output.is_file():
        existing = minute_file(output)
        minutes = pd.concat([existing, minutes]).dropna(axis=1).sort_index(kind="stable")
        minutes = minutes.loc[~minutes.index.duplicated(keep="last")]
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, suffix=".parquet", delete=False) as temp:
        staged = Path(temp.name)
    try:
        minutes.to_parquet(staged)
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    return minutes


def download_delta_funding(start, end):
    start = start.ceil("h")
    end = min(end.ceil("h"), pd.Timestamp.now(tz="UTC").floor("h"))
    frame = delta_history("FUNDING:BTCUSD", "1h", start, end, pd.Timedelta(hours=1)).sort_values("time")
    times = pd.DatetimeIndex(frame.time)
    if times.has_duplicates or (times != times.floor("h")).any():
        raise ValueError("Unexpected funding candle timestamps")
    rates = frame[["open", "high", "low", "close"]].astype(float)
    if not np.isfinite(rates.to_numpy()).all() or not rates.eq(rates.open, axis="index").all().all():
        raise ValueError("Funding candles change intrabar. Supply verified exact settlements for this period")
    boundary = times.hour % 8 == 0
    changed = rates.open.diff().fillna(0).ne(0)
    if (changed & ~boundary).any():
        raise ValueError("Funding changes outside 00:00, 08:00 or 16:00 UTC. Verify the venue schedule")
    selected = pd.DataFrame({"settled_at": times[boundary], "rate": rates.open.to_numpy()[boundary] / 100})
    expected = pd.date_range(start.ceil("8h"), end, freq="8h", inclusive="left")
    if not len(expected) or not pd.DatetimeIndex(selected.settled_at).equals(expected):
        raise ValueError("Missing settlement data or no complete funding boundaries in the requested period")
    return selected


def download_delta_open_interest(start, end):
    interval = pd.Timedelta(hours=1)
    frame = delta_history("OI:BTCUSD", "1h", start.floor("h"),
                          min(end.ceil("h"), pd.Timestamp.now(tz="UTC").floor("h")), interval)
    frame = frame.set_index("time").sort_index()
    if frame.index.has_duplicates or (frame.index != frame.index.floor("h")).any():
        raise ValueError("Unexpected open-interest candle timestamps")
    close = pd.to_numeric(frame.close).where(lambda values: np.isfinite(values) & values.gt(0))
    change = close.pct_change(fill_method=None).where(frame.index.to_series().diff().eq(interval))
    observations = change.dropna().rename("value").reset_index()
    observations["available_at"] = observations.pop("time") + interval + pd.Timedelta(seconds=1)
    observations["metric"] = "oi_change_1h"
    observations["source"] = "delta_open_interest_history"
    return observations.loc[observations.available_at.ge(start) & observations.available_at.lt(end),
                            ["available_at", "metric", "value", "source"]]


def derivatives_snapshot():
    observations = []
    failures = {}

    def record(source, values):
        seen = pd.Timestamp.now(tz="UTC")
        observations.extend({"available_at": seen.isoformat(), "metric": key, "value": float(value), "source": source}
                            for key, value in values.items() if value is not None and np.isfinite(float(value)))

    with requests.Session() as session:
        def collect(name, url, params, transform):
            try:
                record(name, transform(get_json(session, url, params)))
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as error:
                failures[name] = str(error)

        def delta_ticker(data):
            ticker = data["result"]
            funding = ticker.get("funding_rate")
            return {"delta_open_interest": ticker.get("oi"), "delta_mark": ticker.get("mark_price"),
                    "funding_rate": float(funding) / 100 if funding is not None else None}

        collect("delta_ticker", f"{DELTA}/tickers/BTCUSD", None, delta_ticker)
        collect("binance_premium", f"{BINANCE}/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"},
                lambda data: {"premium": float(data["markPrice"]) / float(data["indexPrice"]) - 1})

        def latest(data):
            return max(data, key=lambda row: int(row["timestamp"]))

        def oi_change(data):
            last = latest(data)
            target = int(last["timestamp"]) - 3_600_000
            earlier = next((row for row in data if int(row["timestamp"]) == target), None)
            return {"oi_change_1h": float(last["sumOpenInterest"]) / float(earlier["sumOpenInterest"]) - 1
                    if earlier else None}

        queries = {
            "openInterestHist": oi_change,
            "globalLongShortAccountRatio": lambda data: {"long_short_ratio": latest(data)["longShortRatio"]},
            "topLongShortAccountRatio": lambda data: {"top_long_short_ratio": latest(data)["longShortRatio"]},
            "takerlongshortRatio": lambda data: {"taker_ratio": latest(data)["buySellRatio"]},
        }
        for endpoint, transform in queries.items():
            collect(f"binance_{endpoint}", f"{BINANCE}/futures/data/{endpoint}",
                    {"symbol": "BTCUSDT", "period": "5m", "limit": 13 if endpoint == "openInterestHist" else 1},
                    transform)
        from .daily_context import daily_context
        daily, errors = daily_context(session)
        observations.extend(daily)
        failures.update(errors)
    return observations, failures
