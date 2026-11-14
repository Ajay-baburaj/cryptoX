"""Frozen-rule replications: (a) same-TF bar walk on Binance, (b) Delta BTCUSD 2026 1m."""
import json, sys
import numpy as np, pandas as pd
from common import RES, ROOT, load_binance, bars, funding_cum
from protocol import *
from smart_zone import compute_signals, preset
from sim import Walk, sim_all, sequential, net_r, metrics

SEL = json.loads((RES / "selection.json").read_text())
EX = {"R0.5": ("R", .5), "R1.0": ("R", 1.), "R1.5": ("R", 1.5), "R2.0": ("R", 2.), "opp": ("opp", None), "time10": ("time", 10), "time30": ("time", 30)}
def rules():
    for tf in TIMEFRAMES:
        for p in PRESETS:
            yield f"baseline_{tf}m_{p}", tf, p, "all", "all", EX["R1.0"], .25
        s = SEL[str(tf)]
        if s:
            yield f"selected_{tf}m", tf, s["preset"], s["zone"], s["stars"], EX[s["exit"]], float(s["buffer"])

def mask(sig, zone, star):
    k = sig["kind"]; mk = np.ones(len(k), bool) if zone == "all" else (k == "sup") if zone == "sup" else (k == "res") if zone == "res" else np.isin(k, ["SR", "RS"])
    if star != "all": mk &= sig["stars"] == int(star)
    return mk

def segments(idx, gap="60min"):
    br = np.flatnonzero(np.diff(idx.values) > np.timedelta64(pd.Timedelta(gap)))
    a = np.r_[0, br + 1]; b = np.r_[br, len(idx) - 1]
    return list(zip(a, b))

def run(tag_rows, m, walk, label, tfwalk=False):
    pass

rows = []
# (a) same-TF walk Binance, entries by split
m, f = load_binance(); fc = funding_cum(m.index, f)
for tag, tf, p, zone, star, ex, b in rules():
    df = bars(m, tf); P = preset(p)
    sig = compute_signals(*[df[c].values for c in ("open", "high", "low", "close")], P)
    keep = sig["i"].astype(int) + 1 < len(df); sig = {k: v[keep] for k, v in sig.items()}
    ent = sig["i"].astype(int) + 1; w = Walk(df.open.values, df.high.values, df.low.values, df.close.values, fc[m.index.searchsorted(df.index)])
    ord_ = np.lexsort((-sig["score"], ent)); sig = {k: v[ord_] for k, v in sig.items()}; ent = ent[ord_]
    for sp, (x, y) in SPLITS.items():
        A = df.index.searchsorted(pd.Timestamp(x, tz="UTC")); B = df.index.searchsorted(pd.Timestamp(y, tz="UTC")) - 1
        if A > B: continue
        cap = np.where((ent >= A) & (ent <= B), B, -1)
        s = sim_all(w, sig, ent, cap, 1, ex, b)
        ix = sequential(ent, s["x"], np.flatnonzero(mask(sig, zone, star) & s["ok"] & (cap >= 0)))
        R, sf = net_r(w, sig, ent, s, ix, COSTS["base"])
        rows.append(dict(set="binance_tf_walk", tag=tag, split=sp, **metrics(R, sf)))
pd.DataFrame(rows).to_csv(RES / "tf_walk.csv", index=False)
print(pd.DataFrame(rows).round(3).to_string())

# (b) Delta
dm = pd.read_parquet(ROOT / "data/parquet/BTCUSD_1m_20260101_20261026.parquet")
gaps = dm.index.to_series().diff().dropna(); big = gaps[gaps > pd.Timedelta("1min")]
print("delta 1m rows", len(dm), dm.index[0], dm.index[-1], "missing-gap count", len(big), "minutes missing approx", int((big / pd.Timedelta("1min") - 1).sum()), "largest", big.nlargest(5).to_dict())
segs = [(a, b) for a, b in segments(dm.index) if (b - a) > 7 * 1440]
print("segments", [(str(dm.index[a]), str(dm.index[b])) for a, b in segs])
rows2 = []
for tag, tf, p, zone, star, ex, b in rules():
    Rs, sfs, ent_all = [], [], []
    for a, z in segs:
        seg = dm.iloc[a:z + 1]; df = bars(seg, tf)
        if len(df) < 300: continue
        sig = compute_signals(*[df[c].values for c in ("open", "high", "low", "close")], preset(p))
        if len(sig["i"]) == 0: continue
        keep = sig["i"].astype(int) + 1 < len(df); sig = {k: v[keep] for k, v in sig.items()}
        w = Walk(seg.open.values, seg.high.values, seg.low.values, seg.close.values, np.zeros(len(seg)))
        ent = seg.index.searchsorted(df.index[sig["i"].astype(int) + 1])
        o = np.lexsort((-sig["score"], ent)); sig = {k: v[o] for k, v in sig.items()}; ent = ent[o]
        cap = np.full(len(ent), len(seg) - 1)
        s = sim_all(w, sig, ent, cap, tf, ex, b)
        ix = sequential(ent, s["x"], np.flatnonzero(mask(sig, zone, star) & s["ok"]))
        for cn in ("zero", "maker_entry", "base"):
            c = list(COSTS[cn]); c[4] = False
            R, sf = net_r(w, sig, ent, s, ix, tuple(c))
            Rs.append((cn, R)); sfs.append((cn, sf))
    for cn in ("zero", "maker_entry", "base"):
        R = np.concatenate([r for c, r in Rs if c == cn]) if Rs else np.array([])
        sf = np.concatenate([r for c, r in sfs if c == cn]) if Rs else np.array([])
        rows2.append(dict(set="delta_2026_no_funding", tag=tag, cost=cn, **metrics(R, sf)))
pd.DataFrame(rows2).to_csv(RES / "delta_replication.csv", index=False)
print(pd.DataFrame(rows2).round(3).to_string())
