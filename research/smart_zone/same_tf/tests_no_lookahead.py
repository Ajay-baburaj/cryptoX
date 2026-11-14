"""Run: .venv/bin/python research/smart_zone/same_tf/tests_no_lookahead.py"""
import numpy as np
from common import load_binance, bars
from smart_zone import compute_signals, preset
from sim import Walk, one


def arrs(df):
    return [df[c].values for c in ("open", "high", "low", "close")]


def same_prefix(a, b, k):
    ma, mb = a["i"] <= k, b["i"] <= k
    assert ma.sum() == mb.sum(), (ma.sum(), mb.sum())
    for key in a:
        x, y = a[key][ma], b[key][mb]
        if x.dtype.kind in "fc":
            assert np.allclose(x, y, equal_nan=True), key
        else:
            assert (x == y).all(), key
    return int(ma.sum())


def test_causal():
    m, _ = load_binance(end="2024-09-01")
    total = 0
    for tf, name in [(15, "Balanced"), (60, "Strict"), (240, "Balanced"), (5, "Strict")]:
        df = bars(m, tf).iloc[:30000]
        o, h, l, c = arrs(df)
        p = preset(name)
        full = compute_signals(o, h, l, c, p)
        for k in (len(df) // 4, len(df) // 2, int(len(df) * .85)):
            cut = compute_signals(o[:k + 1], h[:k + 1], l[:k + 1], c[:k + 1], p)
            total += same_prefix(cut, full, k)
            # corrupt all later bars: earlier signals must not change
            rng = np.random.default_rng(k)
            f = 1 + rng.normal(0, .05, len(df) - k - 1)
            o2, h2, l2, c2 = [np.r_[v[:k + 1], v[k + 1:] * f] for v in (o, h, l, c)]
            pert = compute_signals(o2, h2, l2, c2, p)
            same_prefix(pert, full, k)
    assert total > 100, total
    print("causal ok; compared signals:", total)


def test_stop_first():
    o = np.array([100., 100.]); h = np.array([103., 103.]); l = np.array([98., 98.]); c = np.array([100., 100.])
    w = Walk(o, h, l, c, np.zeros(2))
    assert one(w, 0, 1, 99., 102., 1)[2] == 0
    assert one(w, 0, -1, 101., 98.5, 1)[2] == 0
    print("stop-first ok")


if __name__ == "__main__":
    test_stop_first()
    test_causal()
