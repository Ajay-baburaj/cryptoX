"""No-lookahead proof: engine outputs at t are unchanged if future bars are removed or replaced with garbage."""
import numpy as np, engine as E
import pandas as pd
def rec_key(r): return (r["t"], tuple(np.round(r["bot"], 6)), tuple(np.round(r["top"], 6)), tuple(r["stars"]), tuple(r["kind"]), tuple(r["disp"]))
def sub(b, n): return {k: v[:n] for k, v in b.items()}
def zones_upto(b, cfg):
    return E.rebuilds(b, E.find_pivots(b, cfg), cfg)
cfg = E.Cfg(); mn = E.load_minutes("binance"); rng = np.random.default_rng(7); fail = 0; total = 0
for tf in E.TFS:
    b = E.make_bars(mn, E.TFS[tf]); N = min(len(b["c"]), 12000)
    b = sub(b, N); full = zones_upto(b, cfg)
    for T in np.sort(rng.integers(2000, N - 200, 6)):
        bt = sub(b, int(T)); tr = zones_upto(bt, cfg)
        # prefix: every rebuild made by bar T-1 in the full run must be identical in the truncated run
        a = [rec_key(r) for r in full if r["t"] <= T - 1]; c = [rec_key(r) for r in tr if r["t"] <= T - 1]
        same = a == c
        # poison: replace everything after T with garbage; rebuilds <= T-1 must not change
        bp = {k: v.copy() for k, v in b.items()}
        noise = rng.normal(1, 0.3, N - int(T))
        for k in ("o", "h", "l", "c"): bp[k][T:] = bp[k][T:] * noise
        bp["h"][T:] = np.maximum.reduce([bp["h"][T:], bp["l"][T:], bp["o"][T:], bp["c"][T:]]) * 1.001
        bp["l"][T:] = np.minimum.reduce([bp["h"][T:], bp["l"][T:], bp["o"][T:], bp["c"][T:]]) * 0.999
        p = [rec_key(r) for r in zones_upto(bp, cfg) if r["t"] <= T - 1]
        s2 = a == p; total += 1; fail += not (same and s2)
        print(tf, "T", int(T), "prefix rebuilds", len(a), "truncation_identical", same, "poison_identical", s2, flush=True)
# a pivot confirmation must lag by exactly `pivot` bars
piv = E.find_pivots(b, cfg); print("confirm lag all ==5:", bool(((piv[:,1]-piv[:,0])==5).all()))
print("TOTAL", total, "FAILURES", fail)
