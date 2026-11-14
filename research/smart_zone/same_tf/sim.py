"""Exit simulation on a walk series (1m by default). Stop wins same-bar ties."""
import numpy as np
from protocol import MAX_HOLD_BARS, MIN_OPP_RR, RISK_PCT, MAX_LEVERAGE

CHUNK = 1500


class Walk:
    def __init__(self, o, h, l, c, funding_cum, step=1):
        self.o, self.h, self.l, self.c, self.f, self.step = o, h, l, c, funding_cum, step


def one(w, e, d, stop, tgt, last):
    """Enter at open of e; returns exit index, price, reason. tgt may be nan."""
    i = e
    while i <= last:
        j = min(i + CHUNK, last + 1)
        hs = (w.l[i:j] <= stop) if d == 1 else (w.h[i:j] >= stop)
        ht = np.zeros(j - i, bool) if np.isnan(tgt) else ((w.h[i:j] >= tgt) if d == 1 else (w.l[i:j] <= tgt))
        any_s, any_t = hs.any(), ht.any()
        if any_s or any_t:
            a = hs.argmax() if any_s else 1 << 60
            b = ht.argmax() if any_t else 1 << 60
            if a <= b:                      # stop first on ties
                k = i + a
                px = min(w.o[k], stop) if d == 1 else max(w.o[k], stop)
                return k, px, 0
            return i + b, tgt, 1
        i = j
    return last, w.c[last], 2


def sim_all(w, sig, entry, cap, tf_steps, exit_rule, buf):
    """entry/cap are walk indices per signal. tf_steps = walk steps per source bar."""
    n = len(entry)
    out = dict(ok=np.zeros(n, bool), x=np.zeros(n, int), px=np.zeros(n), risk=np.zeros(n), why=np.zeros(n, int))
    kind, val = exit_rule
    for s in range(n):
        e, d = int(entry[s]), int(sig["side"][s])
        if e > cap[s]:
            continue
        op = w.o[e]
        stop = sig["bot"][s] - buf * sig["atr"][s] if d == 1 else sig["top"][s] + buf * sig["atr"][s]
        risk = (op - stop) * d
        if risk <= 0:
            continue
        hold = MAX_HOLD_BARS
        tgt = np.nan
        if kind == "R":
            tgt = op + d * val * risk
        elif kind == "opp":
            tgt = sig["opp"][s]
            if np.isnan(tgt) or (tgt - op) * d < MIN_OPP_RR * risk:
                continue
        else:
            hold = val
        last = min(e + hold * tf_steps - 1, int(cap[s]))
        x, px, why = one(w, e, d, stop, tgt, last)
        out["ok"][s], out["x"][s], out["px"][s], out["risk"][s], out["why"][s] = True, x, px, risk, why
    return out


def sequential(entry, exit_, idx):
    """One position at a time. idx must be sorted by entry time (priority on ties)."""
    keep, free = [], -1
    for s in idx:
        if entry[s] > free:
            keep.append(s)
            free = exit_[s]
    return np.array(keep, dtype=int)


def net_r(w, sig, entry, sim, ix, cost):
    fe, se, fx, sx, fund = cost
    d = sig["side"][ix].astype(float)
    e = w.o[entry[ix].astype(int)]
    x = sim["px"][ix]
    ef, xf = e * (1 + d * se), x * (1 - d * sx)
    pnl = d * (xf - ef) - fe * e - fx * x
    if fund:
        pnl -= d * (w.f[sim["x"][ix]] - w.f[entry[ix].astype(int)]) * e
    return pnl / sim["risk"][ix], sim["risk"][ix] / e


def metrics(R, stopf):
    n = len(R)
    if n == 0:
        return dict(trades=0, win=np.nan, avgR=np.nan, pf=np.nan, mdd=np.nan, ret=np.nan)
    size = np.minimum(RISK_PCT / stopf, MAX_LEVERAGE)
    eq = np.cumprod(1 + np.maximum(size * stopf * R, -.99))
    dd = 1 - eq / np.maximum.accumulate(np.r_[1, eq])[1:]
    g, l = R[R > 0].sum(), -R[R < 0].sum()
    return dict(trades=n, win=float((R > 0).mean()), avgR=float(R.mean()),
                pf=float(g / l) if l > 0 else np.inf, mdd=float(dd.max()), ret=float(eq[-1] - 1))
