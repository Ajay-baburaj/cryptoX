"""Exit simulation on 1m bars. Stop is checked first within a minute; entry at next 1m open after trigger close."""
import numpy as np
import pandas as pd
from config import MAX_HOLD_MIN, MIN_RISK_PCT, COSTS, EXITS

KR = {"fixed_0.5R": .5, "fixed_1R": 1., "fixed_2R": 2.}


class Minutes:
    def __init__(self, df, funding=None):
        self.ts = df.index.values.astype("datetime64[ns]").astype(np.int64)
        self.o, self.h, self.l, self.c = (df[x].values for x in ("open", "high", "low", "close"))
        self.gap_end = np.flatnonzero(np.diff(self.ts) > 60_000_000_000) + 1
        self.fund = np.zeros(len(df))
        if funding is not None:
            ft = funding.time.values.astype("datetime64[ns]").astype(np.int64)
            pos = np.searchsorted(self.ts, ft, "left")
            np.add.at(self.fund, pos[pos < len(df)], funding.last_funding_rate.values[pos < len(df)])
        self.fund = np.cumsum(self.fund)

    def end_of(self, i):
        e = min(i + MAX_HOLD_MIN, len(self.ts))
        p = np.searchsorted(self.gap_end, i, "right")
        return min(e, self.gap_end[p]) if p < len(self.gap_end) else e


def run_exit(m, i, side, stop, target, trail):
    """Returns exit index, exit price. target may be None; trail=(activate_R_px, dist_px) or None."""
    e = m.end_of(i)
    if e <= i:
        return None
    o, h, l = m.o[i:e], m.h[i:e], m.l[i:e]
    if trail:
        act, dist = trail
        if side == 1:
            hh = np.r_[-np.inf, np.maximum.accumulate(h)[:-1]]
            stp = np.where(hh - o[0] >= act, np.maximum(stop, hh - dist), stop)
            hit = l <= stp
        else:
            hh = np.r_[np.inf, np.minimum.accumulate(l)[:-1]]
            stp = np.where(o[0] - hh >= act, np.minimum(stop, hh + dist), stop)
            hit = h >= stp
        if hit.any():
            k = int(np.argmax(hit))
            p = min(o[k], stp[k]) if side == 1 else max(o[k], stp[k])
            return i + k, p
        return e - 1, m.c[e - 1]
    sh = (l <= stop) if side == 1 else (h >= stop)
    ks = int(np.argmax(sh)) if sh.any() else 10**12
    kt = 10**12
    if target is not None:
        th = (h >= target) if side == 1 else (l <= target)
        if th.any():
            kt = int(np.argmax(th))
    if ks == 10**12 and kt == 10**12:
        return e - 1, m.c[e - 1]
    if ks <= kt:
        k = ks
        p = min(o[k], stop) if side == 1 else max(o[k], stop)
        return i + k, p
    return i + kt, target


def build_trades(s, m, cfg):
    """One row per (signal, exit type); independent of other signals (overlap is resolved per variant)."""
    out = []
    ent = np.searchsorted(m.ts, s.close_ns.values)
    valid = ent < len(m.ts)
    valid[valid] = m.ts[ent[valid]] == s.close_ns.values[valid]
    for n, r in enumerate(s.itertuples()):
        if not valid[n]:
            continue
        i = ent[n]; ep = m.o[i]; side = r.side
        stop = r.bot - cfg.stop_buf * r.zone_atr if side == 1 else r.top + cfg.stop_buf * r.zone_atr
        risk = (ep - stop) * side
        if risk <= 0 or risk / ep < MIN_RISK_PCT:
            continue
        for ex in EXITS:
            trail, target = None, None
            if ex in KR:
                target = ep + side * KR[ex] * risk
            elif ex == "next_zone":
                if np.isnan(r.opp_target):
                    continue
                target = float(r.opp_target)
                if (target - ep) * side < 0.5 * risk:
                    continue
            else:
                trail = (risk, r.htf_atr)   # activates at +1R, trails 1 HTF ATR
            res = run_exit(m, i, side, stop, target, trail)
            if res is None:
                continue
            xi, xp = res
            out.append((n, ex, i, xi, ep, xp, risk, side, (xp - ep) * side / risk,
                        (m.fund[xi] - m.fund[i]) * side * ep / risk))
    return pd.DataFrame(out, columns="sig exit entry_i exit_i ep xp risk side gross_R fund_R".split())


def net_R(t, cost):
    ce, cx, f = COSTS[cost]
    return t.gross_R.values - (ce * t.ep.values + cx * t.xp.values) / t.risk.values - (t.fund_R.values if f else 0)


def non_overlap(t):
    """t sorted by entry_i (one exit type, one filter). Returns positional indices taken."""
    e, x = t.entry_i.values, t.exit_i.values
    out, p = [], 0
    while p < len(e):
        out.append(p)
        p = max(int(np.searchsorted(e, x[p], "right")), p + 1)
    return out
