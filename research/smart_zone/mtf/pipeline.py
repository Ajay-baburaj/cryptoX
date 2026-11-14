"""Build all variants' trade tables, optionally in worker processes."""
import itertools
import multiprocessing as mp
import numpy as np
import pandas as pd
import engine as E
import sim as S
from config import *

_G = {}


def load_binance(end=None):
    m = pd.read_parquet(MINUTES)
    f = pd.read_parquet(FUNDING)
    if end is not None:
        m = m[m.index < pd.Timestamp(end, tz="UTC")]
        f = f[f.time < pd.Timestamp(end, tz="UTC")]
    return m, f


def _job(args):
    htf, preset, ltfs, cfg = args
    m, mm = _G["m"], _G["mm"]
    b = E.resample(m, htf)
    snaps = E.build_snapshots(b, cfg, PRESETS[preset])
    out = {}
    for ltf in ltfs:
        L = E.resample(m, ltf)
        s = E.signals(mm.ts, L, snaps, cfg, E.features(m, L))
        if s.empty:
            out[(htf, ltf, preset)] = (s, pd.DataFrame()); continue
        s["first_touch"] = E.first_touch(s, L, snaps, b, cfg.pivot_r)
        out[(htf, ltf, preset)] = (s, S.build_trades(s, mm, cfg))
    return out


def run_grid(m, funding, combos=COMBOS, presets=tuple(PRESETS), cfg=DEFAULT, procs=7):
    global _G
    _G = {"m": m, "mm": S.Minutes(m, funding)}
    jobs = []
    for htf, preset in itertools.product(sorted({c[0] for c in combos}), presets):
        jobs.append((htf, preset, [l for h, l in combos if h == htf], cfg))
    if procs > 1 and len(jobs) > 1:
        with mp.get_context("fork").Pool(min(procs, len(jobs))) as p:
            res = p.map(_job, jobs)
    else:
        res = [_job(j) for j in jobs]
    return {k: v for r in res for k, v in r.items()}


def variant_trades(tables, combo_key, flt, ex):
    s, t = tables[combo_key]
    if s.empty or t.empty:
        return t
    t = t[t.exit == ex].copy()
    t = t[E.filter_masks(s, flt)[t.sig.values]].sort_values("entry_i").reset_index(drop=True)
    keep = S.non_overlap(t)
    t = t.iloc[keep].copy()
    if t.empty:
        return t
    t["time"] = s.close_ns.values[t.sig.values]
    t["time"] = pd.to_datetime(t.time, utc=True)
    return t


def period_mask(t, a, b):
    return (t.time >= pd.Timestamp(a, tz="UTC")) & (t.time < pd.Timestamp(b, tz="UTC"))


def stats(R):
    R = np.asarray(R)
    if len(R) == 0:
        return dict(n=0, mean=np.nan, wr=np.nan, pf=np.nan, sum=0.)
    gw, gl = R[R > 0].sum(), -R[R < 0].sum()
    return dict(n=len(R), mean=R.mean(), wr=(R > 0).mean(), pf=gw / gl if gl else np.inf, sum=R.sum())


def all_variant_rows(tables, cost="base"):
    rows = []
    for (htf, ltf, preset) in tables:
        for flt, ex in itertools.product(FILTERS, EXITS):
            t = variant_trades(tables, (htf, ltf, preset), flt, ex)
            if t.empty:
                continue
            t = t.assign(R=S.net_R(t, cost))
            rows.append(dict(htf=htf, ltf=ltf, preset=preset, flt=flt, exit=ex, trades=t))
    return rows


def boot_mean_ci(t, nb=2000, seed=7):
    """Week-block bootstrap of mean net R per trade. Returns (mean, lo, hi, p_le_0)."""
    if len(t) == 0:
        return np.nan, np.nan, np.nan, np.nan
    wk = t.time.dt.tz_localize(None).dt.to_period("W").astype(str)
    g = t.groupby(wk).R
    s, n = g.sum().values, g.size().values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), (nb, len(s)))
    b = s[idx].sum(1) / n[idx].sum(1)
    return t.R.mean(), *np.percentile(b, [2.5, 97.5]), float((b <= 0).mean())
