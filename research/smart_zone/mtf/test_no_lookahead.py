"""Truncation tests: nothing computed up to time T may change when later data exist."""
import numpy as np
import pandas as pd
import engine as E, sim as S
from config import *


def _snap_eq(a, b):
    assert a[0] == b[0]
    assert len(a[1]) == len(b[1]), (len(a[1]), len(b[1]))
    for x, y in zip(a[1], b[1]):
        assert np.isclose(x.top, y.top) and np.isclose(x.bot, y.bot) and x.role == y.role and x.stars == y.stars


def _data():
    return pd.read_parquet(MINUTES).loc["2025-01-01":"2025-09-30"]


def test_snapshots_truncation():
    m = _data()
    cut = pd.Timestamp("2025-06-15 03:00", tz="UTC")
    for tf in ("1h", "4h", "1D"):
        fb, tb = E.resample(m, tf), E.resample(m[m.index < cut], tf)
        fs = E.build_snapshots(fb, DEFAULT, PRESETS["Balanced"])
        ts = E.build_snapshots(tb, DEFAULT, PRESETS["Balanced"])
        assert len(ts) < len(fs)
        for a, b in zip(ts, fs[:len(ts)]):
            _snap_eq(a, b)


def test_signals_truncation_and_availability():
    m = _data()
    cut = pd.Timestamp("2025-06-15 03:00", tz="UTC")
    for htf, ltf in (("4h", "15m"), ("1h", "5m"), ("1D", "1h")):
        res = []
        for d in (m, m[m.index < cut]):
            L = E.resample(d, ltf)
            sn = E.build_snapshots(E.resample(d, htf), DEFAULT, PRESETS["Balanced"])
            s = E.signals(None, L, sn, DEFAULT, E.features(d, L))
            s["ft"] = E.first_touch(s, L, sn, E.resample(d, htf), DEFAULT.pivot_r)
            res.append(s)
        f, t = res
        assert len(f) > 0
        # strict availability: zone snapshot known at or before trigger bar OPEN
        assert (f.t0.values <= f.ltf_open_ns.values).all()
        cutns = cut.value
        ff = f[f.close_ns < cutns].reset_index(drop=True)
        tt = t[t.close_ns < cutns].reset_index(drop=True)
        assert len(ff) == len(tt) and len(tt) > 0
        for c in ("i", "side", "bot", "top", "stars", "flip", "ema", "volpct", "adx", "ft"):
            np.testing.assert_allclose(ff[c].astype(float).values, tt[c].astype(float).values, err_msg=c,
                                       equal_nan=True)


def test_future_spike_changes_nothing_before():
    m = _data().copy()
    cut = pd.Timestamp("2025-06-15 03:00", tz="UTC")
    m2 = m.copy(); m2.loc[m2.index >= cut, ["high", "open", "close"]] *= 1.5
    L, L2 = E.resample(m, "15m"), E.resample(m2, "15m")
    s1 = E.build_snapshots(E.resample(m, "4h"), DEFAULT, PRESETS["Balanced"])
    s2 = E.build_snapshots(E.resample(m2, "4h"), DEFAULT, PRESETS["Balanced"])
    a = E.signals(None, L, s1, DEFAULT, E.features(m, L))
    b = E.signals(None, L2, s2, DEFAULT, E.features(m2, L2))
    a, b = a[a.close_ns < cut.value], b[b.close_ns < cut.value]
    assert len(a) == len(b) and (a.top.values == b.top.values).all()


def test_stop_first_tie():
    i = pd.date_range("2025-01-01", periods=5, freq="min", tz="UTC")
    df = pd.DataFrame(dict(open=[100.] * 5, high=[100, 103, 100, 100, 100.], low=[100, 97, 100, 100, 100.],
                           close=[100.] * 5, volume=1.), index=i)
    x = S.run_exit(S.Minutes(df), 0, 1, 98.0, 102.0, None)
    assert x == (1, 98.0)


def test_cluster_flip_and_mixed():
    p = lambda price, bar, ty: (price, bar, ty, 100., 1.0, bar + 5)
    t = 200
    z = E.meta([p(1000, 10, 1), p(1010, 20, 1), p(1005, 100, -1)], t, DEFAULT, PRESETS["Balanced"])
    assert z is not None and z.role == 1 and z.flip
    assert E.meta([p(1000, 10, 1), p(1005, 100, -1), p(1010, 150, 1)], t, DEFAULT, PRESETS["Balanced"]) is None
