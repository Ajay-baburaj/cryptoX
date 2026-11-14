"""Causal Smart-Zone engine. Bars are labelled by open time; a bar is usable only at open+duration."""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from config import TF_MIN, EngineCfg, MAX_HOLD_MIN

NS_MIN = 60_000_000_000


def resample(m, tf):
    n = TF_MIN[tf]
    g = m.resample(f"{n}min", label="left", closed="left")
    b = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
              volume=("volume", "sum"), _n=("open", "size"))
    b = b[b._n == n].drop(columns="_n")  # complete bars only
    b["close_time"] = b.index + pd.Timedelta(minutes=n)
    return b


def wilder(x, n):
    a = np.full_like(x, np.nan, dtype=float)
    if len(x) <= n:
        return a
    a[n - 1] = np.nanmean(x[:n])
    for i in range(n, len(x)):
        a[i] = (a[i - 1] * (n - 1) + x[i]) / n
    return a


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    return wilder(np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)]), n)


def adx(h, l, c, n=14):
    up, dn = np.r_[0, np.diff(h)], -np.r_[0, np.diff(l)]
    p, m = np.where((up > dn) & (up > 0), up, 0.), np.where((dn > up) & (dn > 0), dn, 0.)
    tr = atr(h, l, c, n)
    sp, sm = wilder(p, n), wilder(m, n)
    with np.errstate(all="ignore"):
        dx = 100 * abs(sp - sm) / (sp + sm)
    dx0 = np.where(np.isnan(dx), 0., dx)
    out = wilder(dx0, n)
    out[np.isnan(tr)] = np.nan
    return out


def pivots(b, cfg, a):
    """Returns array rows: price, bar, type(+1 hi, -1 lo), atr, reaction, confirm_bar."""
    L, R, h, l = cfg.pivot_l, cfg.pivot_r, b.high.values, b.low.values
    rows = []
    for i in range(L, len(b) - R):
        if np.isnan(a[i]) or a[i] <= 0:
            continue
        if h[i] > h[i - L:i].max() and h[i] >= h[i + 1:i + R + 1].max():
            rows.append((h[i], i, 1, a[i], (h[i] - l[i + 1:i + R + 1].min()) / a[i], i + R))
        if l[i] < l[i - L:i].min() and l[i] <= l[i + 1:i + R + 1].min():
            rows.append((l[i], i, -1, a[i], (h[i + 1:i + R + 1].max() - l[i]) / a[i], i + R))
    rows.sort(key=lambda r: r[5])
    return rows


@dataclass
class Zone:
    bot: float; top: float; role: int; atr: float; strength: float; display: float; stars: int
    flip: bool; last_bar: int; n: int


def stars_of(d):
    return 1 if d < 1.5 else 2 if d < 3 else 3 if d <= 5 else 4


def meta(ps, t, cfg, preset):
    """ps: list of pivot tuples. Returns Zone or None if mixed / too few."""
    if len(ps) < cfg.min_touches:
        return None
    prices = [p[0] for p in ps]
    atrs = sum(p[3] for p in ps) / len(ps)
    hb = [p[1] for p in ps if p[2] == 1]; lb = [p[1] for p in ps if p[2] == -1]
    flip = False
    if hb and lb:
        if max(hb) + cfg.flip_gap <= min(lb):
            role, flip = 1, True   # resistance phase then support phase: role support
        elif max(lb) + cfg.flip_gap <= min(hb):
            role, flip = -1, True
        else:
            return None            # Mixed: hidden
    else:
        role = 1 if lb else -1
    rec = sum(np.exp(-(t - p[1]) / cfg.tau) for p in ps)
    react = sum(p[4] for p in ps) / len(ps)
    s = rec * (0.5 + 0.5 * min(react, 2.0)) + (cfg.flip_bonus if flip else 0.)
    bot, top = min(prices), max(prices)
    w = (top - bot) / atrs
    if w < cfg.floor_width:
        mid = (top + bot) / 2; bot, top = mid - cfg.floor_width * atrs / 2, mid + cfg.floor_width * atrs / 2
        w = cfg.floor_width
    d = s * max(0.0, 1 - cfg.width_pen * w / preset["max_width"])
    return Zone(bot, top, role, atrs, s, d, stars_of(d), flip, max(p[1] for p in ps), len(ps))


def build_zones(active, t, cfg, preset, c):
    """Zones visible at the close of HTF bar t, from the confirmed pivot list `active`."""
    ps = sorted(active, key=lambda r: r[0])
    clusters, cur = [], []
    for p in ps:
        if cur:
            mean_p = sum(x[0] for x in cur) / len(cur); za = sum(x[3] for x in cur) / len(cur)
            if abs(p[0] - mean_p) > cfg.cluster_mult * min(p[3], za):
                clusters.append(cur); cur = []
        cur.append(p)
    if cur:
        clusters.append(cur)
    out = []
    for cl in clusters:
        cl = list(cl)
        while len(cl) >= 2:
            za = sum(x[3] for x in cl) / len(cl)
            if max(x[0] for x in cl) - min(x[0] for x in cl) <= preset["max_width"] * za:
                break
            w = [max(x[4], 1e-6) * np.exp(-(t - x[1]) / cfg.tau) for x in cl]
            ctr = sum(wi * x[0] for wi, x in zip(w, cl)) / sum(w)
            cl.pop(int(np.argmax([abs(x[0] - ctr) for x in cl])))
        z = meta(cl, t, cfg, preset)
        if z is None or z.strength < preset["min_strength"]:
            continue
        if cfg.break_invalidate:
            cs = c[z.last_bar + 1:t + 1]
            if len(cs) and ((z.role == 1 and cs.min() < z.bot) or (z.role == -1 and cs.max() > z.top)):
                continue
        out.append(z)
    out.sort(key=lambda z: -z.display)
    return out[:preset["max_zones"]]


def build_snapshots(b, cfg, preset):
    """List of (close_time_ns, [Zone], htf_atr) for every HTF bar t, using only data up to close of t."""
    a = atr(b.high.values, b.low.values, b.close.values)
    piv = pivots(b, cfg, a)
    c, ct = b.close.values, b.close_time.values.astype("datetime64[ns]").astype(np.int64)
    snaps, active, j = [], [], 0
    for t in range(len(b)):
        while j < len(piv) and piv[j][5] <= t:
            active.append(piv[j]); j += 1
        active = [p for p in active if t - p[1] <= cfg.lookback]
        zones = build_zones(active, t, cfg, preset, c) if t >= 50 else []
        snaps.append((ct[t], zones, a[t]))
    return snaps


def features(m, ltf_bars):
    """Causal filter inputs, keyed to the trigger bar."""
    f = {"ema": ltf_bars.close.ewm(span=200, adjust=False, min_periods=200).mean().values}
    h4 = resample(m, "4h")
    h1 = resample(m, "1h")
    f["adx4h"] = adx(h4.high.values, h4.low.values, h4.close.values)
    f["adx4h_ct"] = h4.close_time.values.astype("datetime64[ns]").astype(np.int64)
    a1 = atr(h1.high.values, h1.low.values, h1.close.values) / h1.close.values
    f["volpct"] = pd.Series(a1).rolling(720, min_periods=240).rank(pct=True).values
    f["vol_ct"] = h1.close_time.values.astype("datetime64[ns]").astype(np.int64)
    return f


def signals(m_ts, ltf, snaps, cfg, feat):
    """Rejection signals. A zone snapshot applies only to LTF bars opening at/after the HTF close."""
    o, h, l, c = ltf.open.values, ltf.high.values, ltf.low.values, ltf.close.values
    a = atr(h, l, c)
    ot = ltf.index.values.astype("datetime64[ns]").astype(np.int64)
    ct = ltf.close_time.values.astype("datetime64[ns]").astype(np.int64)
    rows = []
    for k, (t0, zones, hatr) in enumerate(snaps):
        if not zones:
            continue
        t1 = snaps[k + 1][0] if k + 1 < len(snaps) else np.iinfo(np.int64).max
        i0, i1 = np.searchsorted(ot, t0, "left"), np.searchsorted(ot, t1, "left")
        if i1 <= i0:
            continue
        H, L, C, A = h[i0:i1], l[i0:i1], c[i0:i1], a[i0:i1]
        for z in zones:
            w = z.top - z.bot
            if z.role == 1:
                d = (z.top - L) / w
                ok = (d >= cfg.depth_min) & (d <= cfg.depth_max) & (C >= z.top + cfg.margin_atr * A)
            else:
                d = (H - z.bot) / w
                ok = (d >= cfg.depth_min) & (d <= cfg.depth_max) & (C <= z.bot - cfg.margin_atr * A)
            for off in np.flatnonzero(ok & ~np.isnan(A)):
                i = i0 + off
                opp = [y.bot if z.role == 1 else y.top for y in zones
                       if y.role == -z.role and ((y.bot > c[i]) if z.role == 1 else (y.top < c[i]))]
                tgt = np.nan if not opp else (min(opp) if z.role == 1 else max(opp))
                rows.append((i, z.role, z.bot, z.top, z.atr, hatr, z.display, z.strength, z.stars, z.flip,
                             tgt, t0, z.last_bar, k))
    if not rows:
        return pd.DataFrame()
    s = pd.DataFrame(rows, columns="i side bot top zone_atr htf_atr display strength stars flip opp_target t0 "
                                   "last_bar snap".split())
    s = s.sort_values(["i", "display"], ascending=[True, False]).drop_duplicates("i").reset_index(drop=True)
    s["close_ns"] = ct[s.i.values]
    s["ltf_open_ns"] = ot[s.i.values]
    s["close_px"] = c[s.i.values]
    s["ema"] = feat["ema"][s.i.values]
    j = np.searchsorted(feat["adx4h_ct"], s.close_ns.values, "right") - 1
    s["adx"] = np.where(j >= 0, feat["adx4h"][np.maximum(j, 0)], np.nan)
    j = np.searchsorted(feat["vol_ct"], s.close_ns.values, "right") - 1
    s["volpct"] = np.where(j >= 0, feat["volpct"][np.maximum(j, 0)], np.nan)
    s["hour"] = (s.close_ns.values // (3600 * 10**9)) % 24
    return s


def first_touch(s, ltf, snaps, b_htf, pivot_r):
    """True if no LTF bar touched the zone between its newest pivot's confirmation and the trigger bar."""
    ot = ltf.index.values.astype("datetime64[ns]").astype(np.int64)
    h, l = ltf.high.values, ltf.low.values
    hct = b_htf.close_time.values.astype("datetime64[ns]").astype(np.int64)
    out = np.ones(len(s), bool)
    for n, r in enumerate(s.itertuples()):
        conf = hct[min(r.last_bar + pivot_r, len(hct) - 1)]
        i0 = np.searchsorted(ot, conf, "left")
        if i0 < r.i:
            if r.side == 1:
                out[n] = l[i0:r.i].min() > r.top
            else:
                out[n] = h[i0:r.i].max() < r.bot
    return out


def filter_masks(s, flt):
    long_ok = np.where(s.side == 1, s.close_px > s.ema, s.close_px < s.ema)
    m = {"none": np.ones(len(s), bool), "ema200": long_ok, "adx_le25": s.adx <= 25, "adx_gt25": s.adx > 25,
         "ema200_adx_le25": long_ok & (s.adx <= 25), "session_ldn_ny": s.hour.between(8, 20),
         "session_asia": s.hour < 8, "vol_low": s.volpct <= .5, "vol_high": s.volpct > .5,
         "star2plus": s.stars >= 2, "star3plus": s.stars >= 3, "first_touch": s.first_touch, "flip_only": s.flip}
    return np.asarray(m[flt], bool)
