"""Random-entry benchmark: same month, side, stop %, 1R target, time stop as each real rejection signal."""
import argparse, os, numpy as np, pandas as pd, multiprocessing as mp, engine as E
G = {}
def run(args):
    r, tf, seed = args; mn, b, sig, cfg, months = G["mn"], G["b"], G["sig"], G["cfg"], G["months"]
    rng = np.random.default_rng(seed); out = np.empty((len(sig), 2), np.float32)
    for i, (mon, side, sp) in enumerate(zip(sig.mon.to_numpy(), sig.role.to_numpy(), sig.tr_stop_pct.to_numpy())):
        bars = months[mon]; j = bars[rng.integers(len(bars))]
        ei = int(b["f"][j]); px = b["o"][j]; stop = px * (1 - side * sp); tp = px * (1 + side * sp)
        ee = min(len(mn["m"]), ei + cfg.time_bars * tf); xp, ex = E.trade(mn, side, ei, stop, tp, ee)
        g = (xp / px - 1) * side; f = (mn["cumf"][ex] - mn["cumf"][ei]) * side
        out[i] = (g, (g - cfg.cost - f) / sp)
    return out
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dir"); ap.add_argument("--tfs", default="5m,15m,1h,4h"); ap.add_argument("--reps", type=int, default=500); ap.add_argument("--source", default="binance")
    a = ap.parse_args(); cfg = E.Cfg(); mn = E.load_minutes(a.source); G.update(mn=mn, cfg=cfg)
    for tfn in a.tfs.split(","):
        tf = E.TFS[tfn]; b = E.make_bars(mn, tf); ev = pd.read_parquet(f"{a.dir}/events_{tfn}.parquet")
        s = ev[(ev.arm == 0) & (ev.signal == 1) & ev.disp & ev.tr_net.notna()].reset_index(drop=True)
        s["mon"] = (pd.to_datetime(s.minute.astype("int64") * 60, unit="s", utc=True).dt.strftime("%Y%m")).astype(int)
        bt = (pd.to_datetime(b["t"] * 60, unit="s", utc=True).strftime("%Y%m")).astype(int).to_numpy()
        G.update(b=b, sig=s, months={m: np.where(bt == m)[0] for m in s.mon.unique()})
        with mp.get_context("fork").Pool(8) as p: res = p.map(run, [(r, tf, 91000 + tf * 7 + r) for r in range(a.reps)], chunksize=5)
        m = np.stack(res, 2); s[["t", "minute", "role", "tr_gross", "tr_net", "tr_stop_pct"]].to_parquet(f"{a.dir}/sig_{tfn}.parquet")
        np.save(f"{a.dir}/bench_{tfn}.npy", m); print(tfn, "signals", len(s), m.shape, flush=True)
