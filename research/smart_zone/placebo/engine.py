"""Independent causal re-implementation of the smart-zone spec. See PROTOCOL.md."""
from __future__ import annotations
import multiprocessing as mp, os, sys, argparse, time
from dataclasses import dataclass
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TFS = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
XS = (0.5, 1.0, 2.0)
START = pd.Timestamp("2024-01-01", tz="UTC")

@dataclass(frozen=True)
class Cfg:
    pivot: int = 5; atr_n: int = 14; lookback: int = 500; tol: float = 0.5; max_w: float = 1.0
    min_w: float = 0.1; horizon: int = 300; lock_atr: float = 0.5
    min_depth: float = 0.1; margin: float = 0.05; stop_buf: float = 0.25; time_bars: int = 48
    cost: float = 0.0014; min_s: float = 1.25; top_n: int = 5; flip_gap: int = 5

def load_minutes(source):
    p = {"binance": "data/binance_ob_timeframes/minutes.parquet",
         "delta": "data/parquet/BTCUSD_1m_20260101_20261026.parquet"}[source]
    d = pd.read_parquet(os.path.join(ROOT, p))
    t = d.index.asi8  # resolution may be us
    res = {"ns": 60_000_000_000, "us": 60_000_000, "ms": 60_000, "s": 60}[d.index.unit]
    m = t // res
    fund = np.zeros(len(d))
    if source == "binance":
        f = pd.read_parquet(os.path.join(ROOT, "data/binance_ob_timeframes/funding.parquet"))
        ft = f["time"].astype("datetime64[us, UTC]").astype("int64").to_numpy() // 60_000_000
        i = np.searchsorted(m, ft)
        ok = (i < len(m)) & (m[np.clip(i, 0, len(m) - 1)] == ft)
        np.add.at(fund, i[ok], f["last_funding_rate"].to_numpy()[ok])
    return dict(m=m, o=d.open.to_numpy(), h=d.high.to_numpy(), l=d.low.to_numpy(), c=d.close.to_numpy(), cumf=np.cumsum(fund))

def make_bars(mn, tf):
    ids = mn["m"] // tf
    u, first, cnt = np.unique(ids, return_index=True, return_counts=True)
    end = np.append(first[1:], len(ids))
    hi = np.maximum.reduceat(mn["h"], first); lo = np.minimum.reduceat(mn["l"], first)
    k = cnt == tf
    return dict(t=u[k] * tf, o=mn["o"][first[k]], h=hi[k], l=lo[k], c=mn["c"][end[k] - 1], f=first[k], e=end[k])

def atr(b, n=14):
    pc = np.r_[np.nan, b["c"][:-1]]
    tr = np.nanmax(np.c_[b["h"] - b["l"], np.abs(b["h"] - pc), np.abs(b["l"] - pc)], axis=1)
    a = np.full(len(tr), np.nan)
    if len(tr) >= n:
        a[n - 1] = tr[:n].mean()
        for i in range(n, len(tr)): a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a

def find_pivots(b, cfg):
    L = cfg.pivot; a = atr(b, cfg.atr_n); w = 2 * L + 1
    out = []
    H, Lo = b["h"], b["l"]
    if len(H) < w: return np.zeros((0, 6))
    ph = np.lib.stride_tricks.sliding_window_view(H, w); pl = np.lib.stride_tricks.sliding_window_view(Lo, w)
    hi = np.where((ph.max(1) == ph[:, L]) & ((ph == ph[:, L][:, None]).sum(1) == 1))[0] + L
    lo = np.where((pl.min(1) == pl[:, L]) & ((pl == pl[:, L][:, None]).sum(1) == 1))[0] + L
    for i, s in [(x, 1) for x in hi] + [(x, -1) for x in lo]:
        if not np.isfinite(a[i]) or a[i] <= 0: continue
        if s == 1: r = (H[i] - Lo[i + 1:i + L + 1].min()) / a[i]; p = H[i]
        else: r = (H[i + 1:i + L + 1].max() - Lo[i]) / a[i]; p = Lo[i]
        out.append((i, i + L, p, s, a[i], max(r, 1e-6)))
    arr = np.array(out, float) if out else np.zeros((0, 6))
    return arr[np.argsort(arr[:, 1], kind="stable")] if len(arr) else arr

def build_zones(P, now, cfg):
    if not len(P): return None
    P = P[np.argsort(P[:, 2], kind="stable")]
    cl, cur = [], [0]
    for j in range(1, len(P)):
        if P[j, 2] - P[cur, 2].max() <= cfg.tol * min(P[j, 4], P[cur, 4].mean()): cur.append(j)
        else: cl.append(cur); cur = [j]
    cl.append(cur)
    rows = []
    for c in cl:
        Q = P[c]; rec = np.exp(-(now - Q[:, 0]) / (cfg.lookback / 2)); wt = Q[:, 5] * rec
        center = float((wt * Q[:, 2]).sum() / wt.sum()); mean_atr = float(Q[:, 4].mean())
        lo, hi = Q[:, 2].min(), Q[:, 2].max()
        if hi - lo > cfg.max_w * mean_atr:
            lo, hi = center - cfg.max_w * mean_atr / 2, center + cfg.max_w * mean_atr / 2
            k = (Q[:, 2] >= lo) & (Q[:, 2] <= hi)
            if not k.any(): k = np.abs(Q[:, 2] - center) == np.abs(Q[:, 2] - center).min()
            Q = Q[k]; rec = rec[k]
        if hi - lo < cfg.min_w * mean_atr:
            mid = (hi + lo) / 2; lo, hi = mid - cfg.min_w * mean_atr / 2, mid + cfg.min_w * mean_atr / 2
        o = np.argsort(Q[:, 0], kind="stable"); ty = Q[o, 3]; ix = Q[o, 0]
        ch = np.where(ty[1:] != ty[:-1])[0]
        if len(ch) == 0: kind = 0 if ty[0] == -1 else 1
        elif len(ch) == 1 and ix[ch[0] + 1] - ix[ch[0]] >= cfg.flip_gap: kind = 2 if ty[0] == -1 else 3
        else: kind = 4
        flip = kind in (2, 3)
        react = float(Q[:, 5].mean()); s = float(rec.sum()) * float(np.clip(react, 0, 3)) * (1.25 if flip else 1.0)
        stars = int(s >= 1.5) + int(s >= 3) + int(s >= 5)
        rows.append((lo, hi, stars, len(Q), react, flip, s, kind))
    z = np.array(rows, float)
    disp = np.zeros(len(z), bool)
    ok = np.where((z[:, 7] != 4) & (z[:, 6] >= cfg.min_s))[0]
    disp[ok[np.argsort(-z[ok, 6], kind="stable")[:cfg.top_n]]] = True
    return np.c_[z, disp.astype(float)]

def rebuilds(b, piv, cfg, hindsight=False):
    """List of rebuild records. A record built at bar t uses only bars <= t (pivots with vis <= t)."""
    vis = piv[:, 0] if hindsight else piv[:, 1]
    if hindsight: 
        o = np.argsort(vis, kind="stable"); piv = piv[o]; vis = vis[o]
    a = atr(b, cfg.atr_n); recs = []; next_id = 0; prev = None
    ts = np.unique(vis).astype(int)
    for t in ts:
        if t >= len(b["c"]) or not np.isfinite(a[t]): continue
        end = int(np.searchsorted(vis, t, side="right")); P = piv[:end]
        P = P[P[:, 0] >= t - cfg.lookback]
        z = build_zones(P, t, cfg)
        if z is None: continue
        lin = np.full(len(z), -1, int)
        if prev is not None and len(prev["bot"]):
            used = np.zeros(len(prev["bot"]), bool)
            for i in np.argsort(-z[:, 6], kind="stable"):
                ov = np.minimum(z[i, 1], prev["top"]) - np.maximum(z[i, 0], prev["bot"]); ov[used] = -1
                j = int(np.argmax(ov))
                if ov[j] > 0: lin[i] = prev["lin"][j]; used[j] = True
        for i in np.where(lin < 0)[0]: lin[i] = next_id; next_id += 1
        rec = dict(t=int(t), bot=z[:, 0], top=z[:, 1], stars=z[:, 2].astype(int), touches=z[:, 3].astype(int),
                   react=z[:, 4], flip=z[:, 5].astype(bool), strength=z[:, 6], kind=z[:, 7].astype(int), disp=z[:, 8].astype(bool), lin=lin, close=float(b["c"][t]), atr=float(a[t]))
        recs.append(rec); prev = rec
    return recs

def placebo_arm(recs, kind, rng, tfmin):
    """Return per-rebuild (bot, top); lineages keep a fixed placebo centre (random) / donor geometry (shuffled)."""
    births, seen = [], set()
    for r in recs:
        for i in range(len(r["lin"])):
            l = int(r["lin"][i])
            if l in seen: continue
            seen.add(l); births.append((r["t"], (0.5 * (r["bot"][i] + r["top"][i]) - r["close"]) / r["atr"], (r["top"][i] - r["bot"][i]) / r["atr"]))
    B = np.array(births) if births else np.zeros((0, 3))
    gap = int(30 * 1440 / tfmin); state = {}; out = []
    for r in recs:
        n = len(r["lin"]); bot, top = np.empty(n), np.empty(n)
        c, a = r["close"], r["atr"]
        rm = 0.5 * (r["bot"] + r["top"]); rw = r["top"] - r["bot"]
        for i in range(n):
            l = int(r["lin"][i])
            if kind == "random":
                if l not in state:
                    d = abs(rm[i] - c)
                    for _ in range(10):
                        cand = c + rng.choice((-1.0, 1.0)) * d * rng.uniform(0.7, 1.3)
                        lo, hi = cand - rw[i] / 2, cand + rw[i] / 2
                        if not ((lo <= r["top"]) & (hi >= r["bot"])).any(): break
                    state[l] = float(cand)
                bot[i] = state[l] - rw[i] / 2; top[i] = state[l] + rw[i] / 2
            else:
                if l not in state:
                    k = B[np.abs(B[:, 0] - r["t"]) >= gap] if len(B) else B
                    if not len(k): k = B
                    pick = k[rng.integers(len(k))]
                    state[l] = (c + pick[1] * a, pick[2] * a)
                m, w = state[l]
                if kind == "shuffled_wm": w = rw[i]
                bot[i] = m - w / 2; top[i] = m + w / 2
        out.append((r["t"], bot, top))
    return out

COLS = ["t", "minute", "role", "stars", "touches", "react", "flip", "kind", "disp", "w_atr", "atr_pct", "signal"]
for x in XS: COLS += [f"y{x}", f"g{x}"]
COLS += ["tr_gross", "tr_net", "tr_stop_pct", "tr_entry"]

def first(a, i0, i1, lv, up):
    step, i = 2000, i0
    while i < i1:
        seg = a[i:min(i1, i + step)]; m = (seg >= lv) if up else (seg <= lv)
        if m.any(): return i + int(m.argmax())
        i += step; step *= 2
    return -1

def trade(mn, side, entry_i, stop, tp, end_i):
    i_s = first(mn["l" if side > 0 else "h"], entry_i, end_i, stop, side < 0)
    i_t = first(mn["h" if side > 0 else "l"], entry_i, end_i, tp, side > 0)
    if i_s >= 0 and (i_t < 0 or i_s <= i_t):
        o = mn["o"][i_s]; px = min(stop, o) if side > 0 else max(stop, o); ex = i_s
    elif i_t >= 0: px, ex = tp, i_t
    else: ex = end_i - 1; px = mn["c"][ex]
    return px, ex

def simulate(b, mn, cfg, recs, zones, tfmin, a, type_filter=True):
    O, H, L, C = b["o"], b["h"], b["l"], b["c"]; n = len(C); rows = []; locks = []
    m_start = int(np.searchsorted(b["t"], int(START.value // 60_000_000_000)))
    for ri, (tb, bot, top) in enumerate(zones):
        tl = zones[ri + 1][0] if ri + 1 < len(zones) else n - 1
        if not len(bot): continue
        rec = recs[ri]
        for t in range(tb + 1, tl + 1):
            pc = C[t - 1]; aa = a[t - 1]
            if locks:
                locks = [(lo, hi) for lo, hi in locks if not (pc > hi + cfg.lock_atr * aa or pc < lo - cfg.lock_atr * aa)]
            sup = (pc > top) & (L[t] <= top); res = (pc < bot) & (H[t] >= bot)
            if not (sup.any() or res.any()): continue
            ids = np.where(sup | res)[0]
            for i in ids[np.lexsort((-rec["strength"][ids], ~rec["disp"][ids]))]:
                lo, hi = bot[i], top[i]
                if any(lo <= h and hi >= l for l, h in locks): continue
                locks.append((lo, hi))
                if t < m_start or not np.isfinite(aa) or aa <= 0: continue
                role = 1 if sup[i] else -1  # 1 = support (long fade)
                f0, f1 = int(b["f"][t]), int(b["e"][t])
                hit = first(mn["l"], f0, f1, hi, False) if role == 1 else first(mn["h"], f0, f1, lo, True)
                if hit < 0: continue
                row = {c: np.nan for c in COLS}
                row.update(t=t, minute=int(mn["m"][hit]), role=role, stars=rec["stars"][i], touches=rec["touches"][i], react=rec["react"][i],
                           flip=rec["flip"][i], kind=rec["kind"][i], disp=rec["disp"][i], w_atr=(hi - lo) / aa, atr_pct=aa / C[t - 1], signal=0)
                s0 = hit + 1; s1 = min(len(mn["m"]), s0 + cfg.horizon * tfmin)
                edge = hi if role == 1 else lo; W = hi - lo
                for x in XS:
                    if role == 1: up, dn = hi + x * aa, lo - x * aa; iu = first(mn["h"], s0, s1, up, True); id_ = first(mn["l"], s0, s1, dn, False)
                    else: up, dn = lo - x * aa, hi + x * aa; iu = first(mn["l"], s0, s1, up, False); id_ = first(mn["h"], s0, s1, dn, True)
                    if iu < 0 and id_ < 0:
                        y = np.nan; g = (mn["c"][s1 - 1] - edge) * role / edge if s1 > s0 else np.nan
                    elif id_ >= 0 and (iu < 0 or id_ <= iu): y = 0.0; g = -(x * aa + W) / edge
                    else: y = 1.0; g = x * aa / edge
                    row[f"y{x}"] = y; row[f"g{x}"] = g
                d = (hi - L[t]) if role == 1 else (H[t] - lo)
                ok = (L[t] >= lo) if role == 1 else (H[t] <= hi)
                conf = (C[t] >= hi + cfg.margin * aa) if role == 1 else (C[t] <= lo - cfg.margin * aa)
                kind_ok = (not type_filter) or (rec["kind"][i] in (0, 3) if role == 1 else rec["kind"][i] in (1, 2))
                if d >= cfg.min_depth * W and ok and conf and kind_ok and t + 1 < n:
                    row["signal"] = 1
                    ei = int(b["f"][t + 1]); px = O[t + 1]
                    stop = (lo - cfg.stop_buf * aa) if role == 1 else (hi + cfg.stop_buf * aa)
                    risk = (px - stop) * role
                    if risk > 0:
                        tp = px + risk * role
                        ee = min(len(mn["m"]), ei + cfg.time_bars * tfmin)
                        xpx, ex = trade(mn, role, ei, stop, tp, ee)
                        gross = (xpx / px - 1) * role
                        fund = (mn["cumf"][ex] - mn["cumf"][ei]) * role
                        row.update(tr_gross=gross, tr_net=gross - cfg.cost - fund, tr_stop_pct=risk / px, tr_entry=ei)
                rows.append(row)
    return rows

G = {}
def _job(job):
    tfmin, arm, rep, seed = job
    b, mn, cfg, recs, a = G["b"], G["mn"], G["cfg"], G["recs"], G["a"]
    if arm == 0: zones = [(r["t"], r["bot"], r["top"]) for r in recs]; use = recs
    elif arm == 3: use = G["hind"]; zones = [(r["t"], r["bot"], r["top"]) for r in use]
    else:
        zones = placebo_arm(recs, {1: "random", 2: "shuffled", 4: "shuffled_wm"}[arm], np.random.default_rng(seed), tfmin); use = recs
    rows = simulate(b, mn, cfg, use, zones, tfmin, a, type_filter=arm in (0, 3))
    d = pd.DataFrame(rows, columns=COLS)
    d.insert(0, "arm", arm); d.insert(1, "rep", rep)
    return d

def run_tf(tfname, source, cfg, reps, out, seed0=20261108, only_arm4=False):
    tf = TFS[tfname]; t0 = time.time()
    G["mn"] = mn = G.get("mn") or load_minutes(source)
    G["b"] = b = make_bars(mn, tf); G["cfg"] = cfg; G["a"] = atr(b, cfg.atr_n)
    piv = find_pivots(b, cfg); G["recs"] = rebuilds(b, piv, cfg); G["hind"] = rebuilds(b, piv, cfg, hindsight=True)
    print(tfname, "bars", len(b["c"]), "pivots", len(piv), "rebuilds", len(G["recs"]), f"{time.time()-t0:.0f}s", flush=True)
    jobs = [(tf, 0, 0, 0), (tf, 3, 0, 0)]
    for r in range(reps):
        jobs += [(tf, 1, r, seed0 + 1000 * tf + 2 * r), (tf, 2, r, seed0 + 1000 * tf + 2 * r + 1)]
    if only_arm4: jobs = [(tf, 4, r, seed0 + 2000000 + 1000 * tf + r) for r in range(reps)]
    with mp.get_context("fork").Pool(8) as p:
        ds = p.map(_job, jobs, chunksize=1)
    ev = pd.concat(ds, ignore_index=True); os.makedirs(out, exist_ok=True)
    if only_arm4: ev = pd.concat([pd.read_parquet(f"{out}/events_{tfname}.parquet"), ev], ignore_index=True)
    ev.to_parquet(f"{out}/events_{tfname}.parquet")
    print(tfname, "events", ev.groupby("arm").size().to_dict(), f"{time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--profile", default="balanced"); ap.add_argument("--pivot", type=int, default=5)
    ap.add_argument("--source", default="binance"); ap.add_argument("--reps", type=int, default=20); ap.add_argument("--tfs", default="5m,15m,1h,4h"); ap.add_argument("--arm4", action="store_true")
    a = ap.parse_args()
    cfg = Cfg(pivot=a.pivot, max_w=0.6 if a.profile == "strict" else 1.0, min_s=1.75 if a.profile == "strict" else 1.25, top_n=3 if a.profile == "strict" else 5)
    out = os.path.join(os.path.dirname(__file__), "output", f"{a.source}_{a.profile}_p{a.pivot}")
    if a.source == "delta": START = pd.Timestamp("2026-03-01", tz="UTC")
    for tf in a.tfs.split(","): run_tf(tf, a.source, cfg, a.reps, out, only_arm4=a.arm4)
