import numpy as np, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RES = HERE / "results"


def load_binance(end=None):
    m = pd.read_parquet(ROOT / "data/binance_ob_timeframes/minutes.parquet")
    f = pd.read_parquet(ROOT / "data/binance_ob_timeframes/funding.parquet")
    if end:
        m = m[m.index < pd.Timestamp(end, tz="UTC")]
    return m, f


def bars(m, tf):
    if tf == 1:
        return m
    b = m.resample(f"{tf}min", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        n=("open", "count"))
    return b[b.n >= .9 * tf].drop(columns="n")


def funding_cum(minute_index, f):
    """Cumulative funding rate by minute index; applied at settlement minute."""
    arr = np.zeros(len(minute_index))
    t = pd.to_datetime(f["time"], utc=True).dt.floor("min")
    pos = minute_index.searchsorted(pd.DatetimeIndex(t))
    r = f["last_funding_rate"].astype(float).values
    for p, v in zip(pos, r):
        if p < len(arr):
            arr[p] += v
    return np.cumsum(arr)
