"""Scale calibration ONLY (2024 zones, no trade outcomes)."""
import numpy as np, sys
from common import load_binance, bars
from smart_zone import compute_signals, preset
m, _ = load_binance(end="2025-01-01")
for mode in ("close", "excursion"):
  for tf in (60, 240):
    df = bars(m, tf)
    _, z = compute_signals(*[df[c].values for c in ("open","high","low","close")], preset("Balanced", reaction=mode), collect_zones=True)
    z = np.array([x[2:] for x in z], float)
    print(mode, tf, "strength med %.2f p90 %.2f | disp med %.2f | touches mean %.2f | rct med %.2f | width med %.2f" % (np.median(z[:,0]), np.percentile(z[:,0],90), np.median(z[:,1]), z[:,2].mean(), np.median(z[:,3]), np.median(z[:,4])))
