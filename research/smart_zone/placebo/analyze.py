"""Analysis for a split. Writes CSVs to <dir>/results_<split>/ and prints a summary. Conclusions: holdout only."""
import argparse, os, sys, numpy as np, pandas as pd
from math import erfc, sqrt
TFS = ["5m", "15m", "1h", "4h"]; XS = (0.5, 1.0, 2.0); B = 5000; CUT_DEV0, CUT_HO = "2024-01-01", "2025-07-01"; END = "2026-11-01"
COST, COSTL = 0.0014, 0.0012
rng = np.random.default_rng(424242)
def holm(ps):
    ps = np.asarray(ps, float); o = np.argsort(ps); out = np.empty(len(ps)); m = len(ps); mx = 0
    for r, i in enumerate(o): mx = max(mx, ps[i] * (m - r)); out[i] = min(1, mx)
    return out
def bh(ps):
    ps = np.asarray(ps, float); o = np.argsort(ps); m = len(ps); q = ps[o] * m / np.arange(1, m + 1); q = np.minimum.accumulate(q[::-1])[::-1]; out = np.empty(m); out[o] = np.minimum(q, 1); return out
def boot_stat(S, stat):
    if len(S) == 0: return np.full(B, np.nan)
    idx = rng.integers(len(S), size=(B, len(S))); return stat(S[idx].sum(1))
def week_blocks(week, S):
    """Aggregate per-event sums to weekly and 4-week blocks; returns (S1, S4)."""
    d = pd.DataFrame(S); d["w"] = week; g = d.groupby("w").sum(); S1 = g.to_numpy(); d["w4"] = week // 4
    S4 = d.drop(columns="w").groupby("w4").sum().to_numpy(); return S1, S4
def se_stat(S1, S4, stat):
    return float(max(np.nanstd(boot_stat(S1, stat)), np.nanstd(boot_stat(S4, stat))))
def p_z(est, se): return 1.0 if not se or not np.isfinite(se) or se == 0 else erfc(abs(est / se) / sqrt(2))
def rate_diff(a, b):
    """Difference in reaction rate a minus b; a/b = (week, y) arrays."""
    wk = np.r_[a[0], b[0]]; n = len(a[0]); S = np.zeros((len(wk), 4))
    S[:n, 0] = a[1]; S[:n, 1] = 1; S[n:, 2] = b[1]; S[n:, 3] = 1
    S1, S4 = week_blocks(wk, S); f = lambda T: T[:, 0] / T[:, 1] - T[:, 2] / T[:, 3]
    T = S1.sum(0); est = float(T[0] / T[1] - T[2] / T[3]); se = se_stat(S1, S4, f); return est, se
def slope_sums(week, x, y):
    n = len(x); S = np.c_[np.ones(n), x, x * x, y, x * y]; return week, S
def slope_of(T): return (T[:, 0] * T[:, 4] - T[:, 1] * T[:, 3]) / np.where((T[:, 0] * T[:, 2] - T[:, 1] ** 2) == 0, np.nan, T[:, 0] * T[:, 2] - T[:, 1] ** 2)
def load(d, tf):
    e = pd.read_parquet(f"{d}/events_{tf}.parquet"); e["date"] = pd.to_datetime(e.minute.astype("int64") * 60, unit="s", utc=True); e["wk"] = (e.minute.astype("int64") // 10080).astype(int); return e
def split(e, s):
    a, z = {"dev": (CUT_DEV0, CUT_HO), "holdout": (CUT_HO, END)}[s]; return e[(e.date >= a) & (e.date < z)]
def main(d, sp):
    out = f"{d}/results_{sp}"; os.makedirs(out, exist_ok=True); rows, trows, f2, be, yr, vol, sig, h = [], [], [], [], [], [], [], []
    for tf in [t for t in TFS if os.path.exists(f"{d}/events_{t}.parquet")]:
        e = load(d, tf); ee = split(e, sp); dev = split(e, "dev")
        dev0 = dev[dev.arm == 0]
        if not len(dev0): dev0 = ee[ee.arm == 0]  # exploratory runs without a dev span (Delta): cut-offs from the same span
        rq = np.quantile(dev0.react, [.25, .5, .75]); vq = np.quantile(dev0.atr_pct, [1 / 3, 2 / 3])
        D = ee[ee.disp]
        for x in XS:
            for arm, nm in ((1, "random_offset"), (2, "shuffled_time_CONFOUNDED"), (4, "shuffled_time_widthmatched")):
                for label, p in (("displayed", D),):
                    r = p[(p.arm == 0) & p[f"y{x}"].notna()]; pl = p[(p.arm == arm) & p[f"y{x}"].notna()]
                    if not len(pl): continue
                    est, se = rate_diff((r.wk.to_numpy(), r[f"y{x}"].to_numpy()), (pl.wk.to_numpy(), pl[f"y{x}"].to_numpy()))
                    allr = p[p.arm == 0]; allp = p[p.arm == arm]
                    rows.append(dict(tf=tf, X=x, null=nm, n_real=len(r), n_placebo=len(pl), real_rate=r[f"y{x}"].mean(), placebo_rate=pl[f"y{x}"].mean(), diff=est, se=se, lo=est - 1.96 * se, hi=est + 1.96 * se, p=p_z(est, se), unresolved_real=allr[f"y{x}"].isna().mean(), unresolved_pl=allp[f"y{x}"].isna().mean()))
            # breakeven: fade at edge; gross %, cost break-even
            r = D[D.arm == 0]; pl = D[D.arm == 1]; ps = D[D.arm == 2]
            def m(z): return float(z[f"g{x}"].mean())
            d1 = rate_diff((r.wk.to_numpy(), r[f"g{x}"].fillna(0).to_numpy()), (pl.wk.to_numpy(), pl[f"g{x}"].fillna(0).to_numpy()))
            be.append(dict(tf=tf, X=x, n=len(r), real_gross_pct=m(r) * 100, random_gross_pct=m(pl) * 100, shuffled_gross_pct=m(ps) * 100, excess_vs_random_pct=d1[0] * 100, excess_se_pct=d1[1] * 100, breakeven_rt_pct_real=max(m(r), 0) * 100, atr_pct_mean=r.atr_pct.mean() * 100, width_atr_mean=r.w_atr.mean()))
        # F2 monotonicity (all events)
        A = ee.copy(); A["rbin"] = np.digitize(A.react, rq); A["tbin"] = A.touches.clip(1, 4); A["sbin"] = A.stars; A["fbin"] = A.flip.astype(float)
        for x in XS:
            for feat, col, mask in (("stars", "sbin", True), ("touches", "tbin", True), ("reaction", "rbin", True), ("flip", "fbin", None)):
                sub = A[A[f"y{x}"].notna()]
                if col == "fbin": sub = sub[sub.kind != 4]
                r0, p1 = sub[sub.arm == 0], sub[sub.arm == 1]
                w0, S0 = slope_sums(r0.wk.to_numpy(), r0[col].to_numpy(float), r0[f"y{x}"].to_numpy()); w1, S1_ = slope_sums(p1.wk.to_numpy(), p1[col].to_numpy(float), p1[f"y{x}"].to_numpy())
                # raw slope
                g0, g4 = week_blocks(w0, S0); s = float(slope_of(S0.sum(0)[None])[0]); se = se_stat(g0, g4, slope_of)
                for var in ("raw", "excess"):
                    if var == "raw": est, se2 = s, se
                    else:
                        k = S0.shape[1]; wk = np.r_[w0, w1]; SS = np.zeros((len(wk), 2 * k)); SS[:len(w0), :k] = S0; SS[len(w0):, k:] = S1_
                        G1, G4 = week_blocks(wk, SS); f = lambda T: slope_of(T[:, :k]) - slope_of(T[:, k:]); est = float(f(SS.sum(0)[None])[0]); se2 = se_stat(G1, G4, f)
                    f2.append(dict(tf=tf, X=x, feature=feat, variant=var, slope=est, se=se2, lo=est - 1.96 * se2, hi=est + 1.96 * se2, p=p_z(est, se2), n=len(r0)))
                lv = r0.groupby(col)[f"y{x}"].agg(["mean", "count"]); lp = p1.groupby(col)[f"y{x}"].mean()
                for k, v in lv.iterrows(): trows.append(dict(tf=tf, X=x, feature=feat, level=k, real_rate=v["mean"], n=int(v["count"]), random_offset_rate=lp.get(k, np.nan)))
                vals = lv["mean"].to_numpy(); 
                f2[-1]["monotone_increasing"] = bool(np.all(np.diff(vals) > 0)) if len(vals) > 1 else None
        # stability (primary X=1, real vs random offset, displayed)
        x = 1.0; all_d = e[e.disp]; col = "y1.0"
        for y in sorted(set(all_d.date.dt.year)):
            c = all_d[(all_d.date.dt.year == y)]; r = c[(c.arm == 0) & c[col].notna()]; pl = c[(c.arm == 1) & c[col].notna()]
            if len(r) < 30: continue
            est, se = rate_diff((r.wk.to_numpy(), r[col].to_numpy()), (pl.wk.to_numpy(), pl[col].to_numpy()))
            yr.append(dict(tf=tf, year=int(y), n=len(r), real=r[col].mean(), random=pl[col].mean(), diff=est, se=se, lo=est - 1.96 * se, hi=est + 1.96 * se))
        H = D[D.arm.isin([0, 1])]; H = H.assign(vb=np.digitize(H.atr_pct, vq))
        for v, nm in zip((0, 1, 2), ("low", "mid", "high")):
            c = H[H.vb == v]; r = c[(c.arm == 0) & c[col].notna()]; pl = c[(c.arm == 1) & c[col].notna()]
            if len(r) < 30: continue
            est, se = rate_diff((r.wk.to_numpy(), r[col].to_numpy()), (pl.wk.to_numpy(), pl[col].to_numpy()))
            vol.append(dict(tf=tf, vol=nm, n=len(r), real=r[col].mean(), random=pl[col].mean(), diff=est, se=se, lo=est - 1.96 * se, hi=est + 1.96 * se))
        # hindsight, exploratory: confirmation lag removed
        hd = ee[ee.disp]
        for x in XS:
            for arm, nm in ((3, "hindsight"), (0, "causal")):
                r = hd[(hd.arm == arm) & hd[f"y{x}"].notna()]; h.append(dict(tf=tf, X=x, arm=nm, n=len(r), rate=r[f"y{x}"].mean()))
        # F3 signals vs random entries
        bfile = f"{d}/bench_{tf}.npy"
        if os.path.exists(bfile):
            s = pd.read_parquet(f"{d}/sig_{tf}.parquet"); s["date"] = pd.to_datetime(s.minute.astype("int64") * 60, unit="s", utc=True); m = np.load(bfile)
            a, z = {"dev": (CUT_DEV0, CUT_HO), "holdout": (CUT_HO, END)}[sp]; ok = (s.date >= a) & (s.date < z); s2 = s[ok]; m2 = m[ok.to_numpy()]
            real_r = (s2.tr_net / s2.tr_stop_pct).to_numpy(); nul_gross = m2[:, 0, :]; nul_r = m2[:, 1, :]
            if len(s2) >= 5:
                reps = nul_r.mean(0); rmean = float(real_r.mean())
                wk = (s2.minute.astype("int64") // 10080).to_numpy().astype(int); d_i = real_r - nul_r.mean(1)
                S = np.c_[d_i, np.ones(len(d_i))]; G1, G4 = week_blocks(wk, S); fn = lambda T: T[:, 0] / T[:, 1]; est = float(d_i.mean()); se = se_stat(G1, G4, fn)
                p1 = (1 + (reps >= rmean).sum()) / (1 + len(reps))
                gpct = float(s2.tr_gross.mean()) * 100; ngross = float(nul_gross.mean()) * 100
                sig.append(dict(tf=tf, n=len(s2), win=float((real_r > 0).mean()), real_mean_R=rmean, random_mean_R=float(reps.mean()), random_R_p05=float(np.quantile(reps, .05)), random_R_p95=float(np.quantile(reps, .95)), diff_R=est, se=se, lo=est - 1.96 * se, hi=est + 1.96 * se, p_one_sided=p1, real_gross_pct=gpct, random_gross_pct=ngross, breakeven_rt_pct=max(gpct, 0), real_net_pct=float(s2.tr_net.mean()) * 100, mean_stop_pct=float(s2.tr_stop_pct.mean()) * 100))
        print("done", tf, flush=True)
    F1 = pd.DataFrame(rows); F1["holm_family"] = holm(F1.p); F1["bh_family"] = bh(F1.p)
    F2 = pd.DataFrame(f2); F2["holm_family"] = holm(F2.p); F2["bh_family"] = bh(F2.p)
    F3 = pd.DataFrame(sig)
    if len(F3): F3["holm_family"] = holm(F3.p_one_sided); F3["bh_family"] = bh(F3.p_one_sided)
    allp = np.r_[F1.p, F2.p, F3.p_one_sided.values if len(F3) else []]; hg = holm(allp); F1["holm_global"] = hg[:len(F1)]; F2["holm_global"] = hg[len(F1):len(F1) + len(F2)]
    if len(F3): F3["holm_global"] = hg[len(F1) + len(F2):]
    print("TOTAL TESTS", len(allp))
    for nm, tb in (("f1", F1), ("f2", F2), ("f3", F3), ("levels", pd.DataFrame(trows)), ("breakeven", pd.DataFrame(be)), ("year", pd.DataFrame(yr)), ("vol", pd.DataFrame(vol)), ("hindsight", pd.DataFrame(h))): tb.to_csv(f"{out}/{nm}.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 300)
    print(F1[["tf", "X", "null", "n_real", "real_rate", "placebo_rate", "diff", "lo", "hi", "p", "holm_family", "holm_global", "unresolved_real"]].round(4).to_string())
    print(F3.round(4).to_string() if len(F3) else "no F3")
    print(pd.DataFrame(be).round(4).to_string())
    print(pd.DataFrame(yr).round(4).to_string()); print(pd.DataFrame(vol).round(4).to_string()); print(pd.DataFrame(h).round(4).to_string())
    print(F2[(F2.X == 1.0)].round(4).to_string()); print("F2 sig (holm family<.05):"); print(F2[F2.holm_family < .05].round(4).to_string())
    print(pd.DataFrame(trows)[lambda x: x.X == 1.0].round(4).to_string())
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dir"); ap.add_argument("--split", default="dev"); a = ap.parse_args(); main(a.dir, a.split)
