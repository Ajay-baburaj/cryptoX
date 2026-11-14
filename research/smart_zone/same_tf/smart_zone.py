"""Causal reimplementation of Smart Zone Pro [Abusuhil] (Pine source unavailable).

Bar loop processes bars strictly in order; each bar i may read only arrays[<=i].
Order within a bar: (1) test rejection against zones built from pivots confirmed by
i-1, (2) confirm pivot p=i-right, (3) rebuild zones. Assumptions are Params defaults.
"""
from dataclasses import dataclass, replace
import numpy as np


@dataclass(frozen=True)
class Params:
    left: int = 5
    right: int = 5
    atr_len: int = 14
    max_pivots: int = 30
    max_zones: int = 5
    min_strength: float = 1.25
    max_width_atr: float = 1.0
    merge_frac: float = 0.5        # merge distance = merge_frac*max_width*min(ATRs)
    pad_atr: float = 0.1           # zone = pivot span +/- pad, so one pivot has width
    flip_gap: int = 10
    recency_hl: float = 200.0      # bars
    flip_bonus: float = 1.0
    wpen: float = 0.3
    min_depth: float = 0.1         # ATR, wick depth inside zone
    max_beyond: float = 0.25       # ATR, wick may go this far past far edge
    margin: float = 0.05           # ATR, close beyond near edge
    reaction: str = "close"        # close | excursion
    filter_on: str = "display"     # display | strength
    prev_outside: bool = False     # prior close must be outside the zone
    invalidate_atr: float = 0.0    # >0: close this many ATR through far edge kills zone


def preset(name, **kw):
    base = dict(Balanced=dict(max_zones=5, min_strength=1.25, max_width_atr=1.0),
                Strict=dict(max_zones=3, min_strength=1.75, max_width_atr=0.6))[name]
    return replace(Params(**base), **kw)


def wilder_atr(h, l, c, n):
    atr = np.full(len(c), np.nan)
    if len(c) <= n:
        return atr
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])])
    atr[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


class Zone:
    __slots__ = "pivots top bot avg_atr kind role flip rct".split()

    def __init__(self, pivots, p):
        self.pivots = pivots
        self.avg_atr = sum(x[3] for x in pivots) / len(pivots)
        pr = [x[0] for x in pivots]
        pad = p.pad_atr * self.avg_atr
        self.top, self.bot = max(pr) + pad, min(pr) - pad
        self.rct = sum(x[4] for x in pivots) / len(pivots)
        s = [x[1] for x in pivots if x[2] == 1]   # support (pivot low) bars
        r = [x[1] for x in pivots if x[2] == -1]
        self.flip = False
        if s and r:
            if max(s) + p.flip_gap <= min(r):
                self.kind, self.role, self.flip = "SR", -1, True
            elif max(r) + p.flip_gap <= min(s):
                self.kind, self.role, self.flip = "RS", 1, True
            else:
                self.kind, self.role = "mixed", 0
        elif s:
            self.kind, self.role = "sup", 1
        else:
            self.kind, self.role = "res", -1

    def score(self, i, p):
        rec = sum(0.5 ** ((i - x[1]) / p.recency_hl) for x in self.pivots) / len(self.pivots)
        st = len(self.pivots) * (0.5 + 0.5 * self.rct) * rec + (p.flip_bonus if self.flip else 0.0)
        w = (self.top - self.bot) / self.avg_atr
        return st, st - p.wpen * w, w


def build_zones(pivots, i, p):
    """pivots: tuples (price, bar, type, atr, reaction)."""
    clusters = []
    for pv in sorted(pivots, key=lambda x: x[0]):
        if clusters:
            c = clusters[-1]
            ap = sum(x[0] for x in c) / len(c)
            aa = sum(x[3] for x in c) / len(c)
            if abs(pv[0] - ap) <= p.merge_frac * p.max_width_atr * min(pv[3], aa):
                c.append(pv)
                continue
        clusters.append([pv])
    zones = []
    for c in clusters:
        while len(c) > 1:
            aa = sum(x[3] for x in c) / len(c)
            pr = [x[0] for x in c]
            if max(pr) - min(pr) + 2 * p.pad_atr * aa <= p.max_width_atr * aa:
                break
            w = [max(x[4], 1e-3) * 0.5 ** ((i - x[1]) / p.recency_hl) for x in c]
            ctr = sum(a * b for a, b in zip(w, pr)) / sum(w)
            c = sorted(c, key=lambda x: abs(x[0] - ctr))[:-1]
        zones.append(Zone(c, p))
    return zones


def stars(v):
    return 1 if v < 1.5 else 2 if v < 3 else 3 if v <= 5 else 4


def compute_signals(o, h, l, c, p, collect_zones=False):
    n = len(c)
    atr = wilder_atr(h, l, c, p.atr_len)
    pivots, zones, out, seen = [], [], [], []
    start = p.atr_len + p.left + p.right
    for i in range(start, n):
        a = atr[i]
        # (1) signals on zones known before this bar
        if zones:
            scored = []
            for z in zones:
                if z.role == 0:
                    continue
                st, disp, w = z.score(i, p)
                v = disp if p.filter_on == "display" else st
                if v >= p.min_strength:
                    scored.append((v, st, w, z))
            scored.sort(key=lambda x: -x[0])
            vis = scored[:p.max_zones]
            if collect_zones:
                seen += [(i, x[3].kind, x[1], x[0], len(x[3].pivots), x[3].rct, x[2]) for x in vis]
            best = {}
            for v, st, w, z in vis:
                if z.role == 1:
                    depth = z.top - l[i]
                    ok = depth >= p.min_depth * a and l[i] >= z.bot - p.max_beyond * a \
                        and c[i] >= z.top + p.margin * a \
                        and (not p.prev_outside or c[i - 1] > z.top)
                else:
                    depth = h[i] - z.bot
                    ok = depth >= p.min_depth * a and h[i] <= z.top + p.max_beyond * a \
                        and c[i] <= z.bot - p.margin * a \
                        and (not p.prev_outside or c[i - 1] < z.bot)
                if ok and z.role not in best:   # vis is sorted, first is strongest
                    best[z.role] = (v, st, w, z)
            for side, (v, st, w, z) in best.items():
                if side == 1:
                    opp = [y[3].bot for y in vis if y[3].role == -1 and y[3].bot > c[i]]
                    tgt = min(opp) if opp else np.nan
                else:
                    opp = [y[3].top for y in vis if y[3].role == 1 and y[3].top < c[i]]
                    tgt = max(opp) if opp else np.nan
                out.append((i, side, z.top, z.bot, a, z.kind, stars(v), v, st, len(z.pivots), z.rct, w, tgt))
            if p.invalidate_atr > 0:
                dead = [z for z in zones if (z.role == 1 and c[i] < z.bot - p.invalidate_atr * a)
                        or (z.role == -1 and c[i] > z.top + p.invalidate_atr * a)]
                if dead:
                    ids = {x for z in dead for x in z.pivots}
                    pivots = [x for x in pivots if x not in ids]
                    zones = build_zones(pivots, i, p)
        # (2) confirm pivot whose right bars have now all closed
        q = i - p.right
        changed = False
        if q - p.left >= 0 and not np.isnan(atr[q]):
            lo, hi = q - p.left, i
            for typ, arr in ((-1, h), (1, l)):
                x = arr[q]
                right = arr[q + 1:hi + 1]
                left = arr[lo:q]
                is_piv = (x > right.max() and x >= left.max()) if typ == -1 else (x < right.min() and x <= left.min())
                if is_piv:
                    if p.reaction == "close":
                        r = max((x - c[i]) if typ == -1 else (c[i] - x), 0.0) / atr[q]
                    else:
                        r = max((x - l[q + 1:i + 1].min()) if typ == -1 else (h[q + 1:i + 1].max() - x), 0.0) / atr[q]
                    pivots.append((float(x), q, typ, float(atr[q]), float(r)))
                    changed = True
        if changed:
            pivots = pivots[-p.max_pivots:]
            zones = build_zones(pivots, i, p)
    names = "i side top bot atr kind stars score strength touches rct width opp".split()
    res = {k: np.array([r[j] for r in out]) if out else np.array([], dtype=float) for j, k in enumerate(names)}
    return (res, seen) if collect_zones else res
