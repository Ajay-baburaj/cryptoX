"""Join contextual observations using their recorded publication or receipt time."""
from pathlib import Path

import numpy as np
import pandas as pd

from .features import utc_index
from .news import load as load_news

MAX_AGE = {
    "funding_rate": "12h", "oi_change_1h": "90min", "taker_ratio": "20min",
    "long_short_ratio": "20min", "top_long_short_ratio": "20min", "premium": "20min",
    "delta_open_interest": "20min", "delta_mark": "20min", "fear_greed": "2d",
    "etf_net_flow_usd": "4d", "dxy_return": "4d", "nasdaq_return": "4d",
    "real_yield_change": "4d", "dxy_btc_corr30": "4d", "nasdaq_btc_corr30": "4d",
    "mvrv": "3d", "sopr": "3d", "exchange_netflow": "3d", "liquidation_imbalance": "20min",
}


def observations(path):
    if path is None:
        return pd.DataFrame(columns=["available_at", "metric", "value", "source"])
    frame = pd.read_csv(path)
    frame["available_at"] = utc_index(frame["available_at"])
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if not np.isfinite(frame.value).all() or frame.source.isna().any():
        raise ValueError("Context observations need finite values and an identified source")
    if frame.duplicated(["available_at", "metric", "source"]).any():
        raise ValueError("Conflicting or duplicated context observations")
    return frame.sort_values("available_at", kind="stable")


def add_context(matrix, path=None, events=None, news_db=None, funding=None, funding_source="settled_funding"):
    matrix = matrix.copy()
    data = observations(path)
    if funding is not None and not funding.empty:
        # Settled observations can inform later decisions, and remain distinct from provisional funding.
        derived = pd.DataFrame({"available_at": funding.index + pd.Timedelta(seconds=1),
                                "metric": "funding_rate", "value": funding.to_numpy(), "source": funding_source})
        data = pd.concat([data, derived] if not data.empty else [derived], ignore_index=True)
    for metric, samples in data.groupby("metric"):
        if metric not in MAX_AGE:
            continue
        # When several venues report a metric, expose the source and favor the most recently available value.
        samples = samples.sort_values(["available_at", "source"]).drop_duplicates("available_at", keep="last")
        aligned = pd.merge_asof(pd.DataFrame(index=matrix.index),
                                samples.set_index("available_at")[["value", "source"]],
                                left_index=True, right_index=True, tolerance=pd.Timedelta(MAX_AGE[metric]))
        matrix[f"ctx_{metric}"] = aligned.value
        matrix[f"ctx_{metric}_source"] = aligned.source

    matrix["event_blackout"] = False
    if events is not None:
        calendar = pd.read_csv(Path(events))
        event_time, known_at = utc_index(calendar["event_at"]), utc_index(calendar["available_at"])
        if (known_at > event_time).any():
            raise ValueError("Scheduled event availability must precede the event")
        for event, known in zip(event_time, known_at):
            matrix["event_blackout"] |= ((matrix.index >= max(known, event - pd.Timedelta(minutes=30)))
                                          & (matrix.index <= event + pd.Timedelta(minutes=30)))

    news = load_news(news_db)
    if news.empty:
        matrix["news_count"] = 0
        matrix["news_security_count"] = 0
        return matrix
    # Exclude stale headlines from the initial poll when the publisher date is available.
    age = news.available_at - news.published_at
    news = news.loc[age.isna() | age.le(pd.Timedelta("6h"))]
    for key, eligible in (("news_count", news), ("news_security_count", news[news.topic.eq("security_event")])):
        dates = pd.DatetimeIndex(eligible.available_at).sort_values()
        matrix[key] = dates.searchsorted(matrix.index, side="right") - dates.searchsorted(
            matrix.index - pd.Timedelta("6h"), side="right")
    return matrix
