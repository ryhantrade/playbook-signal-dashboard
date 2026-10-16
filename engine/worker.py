"""
Live signal worker: fetch fresh 1H data, resample 4H, run the Playbook
state machine, emit signal JSON to stdout.
Usage: python worker.py <symbol>   (symbol = yfinance ticker)
"""
import os, sys, json, tempfile
import numpy as np
import pandas as pd
import yfinance as yf

symbol = sys.argv[1]
BASE = os.path.dirname(os.path.abspath(__file__))

# ---- fetch ----
df = yf.download(symbol, interval="1h", period="730d", progress=False,
                 auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = [c[0].lower() for c in df.columns]
else:
    df.columns = [c.lower() for c in df.columns]
df = df[["open", "high", "low", "close"]].dropna()
if len(df) < 300:
    print(json.dumps({"market": symbol, "error": "insufficient data"}))
    sys.exit(0)
h4 = df.resample("4h").agg({"open": "first", "high": "max",
                            "low": "min", "close": "last"}).dropna()

tmp = tempfile.mkdtemp()
p1 = os.path.join(tmp, "h1.parquet"); p4 = os.path.join(tmp, "h4.parquet")
df.to_parquet(p1); h4.to_parquet(p4)

os.environ["DATA1H"] = p1
os.environ["DATA4H"] = p4
os.environ.setdefault("TP_RR", "2")
os.environ.setdefault("FEE", "0.0005")
sys.path.insert(0, BASE)

import mm_suite as M
import importlib.util
spec = importlib.util.spec_from_file_location(
    "pb", os.path.join(BASE, "playbook_bt.py"))
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)

h1, h4d = M.h1, M.h4
N = M.N
O, H, L, C, ATR = M.O, M.H, M.L, M.C, M.ATR
T = h1.index
EMA4_10 = h4d["close"].ewm(span=10, adjust=False).mean().to_numpy()

inst = pb.Playbook()
raw = []
for i in range(50, N):
    sig = inst.scan(i)
    if sig:
        raw.append((i, dict(sig)))

def simulate(i, sig):
    d = sig["dir"]; entry, sl, tp = sig["entry"], sig["sl"], sig["tp"]
    for j in range(i + 1, min(N, i + 600)):
        hs = L[j] <= sl if d == 1 else H[j] >= sl
        ht = H[j] >= tp if d == 1 else L[j] <= tp
        if hs and ht:
            px = sl if abs(O[j] - sl) < abs(O[j] - tp) else tp
            return ("sl" if px == sl else "tp", j, px)
        if hs: return ("sl", j, sl)
        if ht: return ("tp", j, tp)
    return ("open", N - 1, C[-1])

sims = []
for (i, sig) in raw:
    res, j, px = simulate(i, sig)
    r = (px - sig["entry"]) / abs(sig["entry"] - sig["sl"]) * (1 if sig["dir"] == 1 else -1)
    sims.append({"time": str(T[i]), "dir": "LONG" if sig["dir"] == 1 else "SHORT",
                 "entry": round(float(sig["entry"]), 4), "sl": round(float(sig["sl"]), 4),
                 "tp": round(float(sig["tp"]), 4), "result": res,
                 "exit_time": str(T[j]) if res != "open" else None,
                 "r": round(float(r), 2)})

i = N - 1
i4 = M.h4_pos[i]
bias = M.htf_bias(i)
d_now = 1 if bias == "bull" else (-1 if bias == "bear" else 0)
ema = EMA4_10[i4]
phase_ok = (d_now == 1 and C[i] < ema) or (d_now == -1 and C[i] > ema)

poi_info = None
if d_now != 0:
    best = None
    for (jb, zlo, zhi, pdir) in pb.POIS:
        if pdir != d_now: continue
        age = i - jb * 4
        if age < 0 or age > 240: continue
        dist = abs(C[i] - (zlo + zhi) / 2)
        if best is None or dist < best[0]:
            best = (dist, zlo, zhi, str(h4d.index[jb]))
    if best:
        dist, zlo, zhi, t4 = best
        at = (d_now == 1 and min(L[max(0, i-4):i+1]) <= zhi + 0.2*ATR[i]) or \
             (d_now == -1 and max(H[max(0, i-4):i+1]) >= zlo - 0.2*ATR[i])
        poi_info = {"zlo": round(float(zlo), 4), "zhi": round(float(zhi), 4),
                    "formed": t4, "at_zone": bool(at),
                    "dist_atr": round(float(abs(C[i]-(zlo+zhi)/2)/ATR[i]), 1)}

st = inst.__dict__.get("st", 0)
STAGE_WAIT = {
    0: "HTF trend + pullback phase + price at a 4H POI",
    5: "Inducement to form while price sits at the POI",
    1: "V-shape liquidity sweep of the inducement pool",
    2: "V confirmation (sharp reversal off the extreme)",
    3: "Market shift (takeout confirming the flip)",
    4: "Retrace into flip/OB zone + momentum candle",
}
sd = inst.__dict__
stage_detail = ""
if st == 5:
    stage_detail = f"POI touched {i - sd.get('poi_bar', i)} bars ago"
elif st == 1 and sd.get("pool"):
    stage_detail = f"Inducement pool @ {sd['pool']:.2f}"
elif st in (2, 3) and sd.get("prot"):
    stage_detail = f"Protected {'low' if sd.get('d')==1 else 'high'} @ {sd['prot']:.2f}"
elif st == 4:
    stage_detail = f"{len(sd.get('zones', []))} zones armed (flip + OB)"

def gs(key, name, state, detail):
    return {"key": key, "name": name, "state": state, "detail": detail}

gates = [
    gs("trend", "HTF trend identified", "pass" if d_now else "fail",
       f"{'Bullish' if d_now==1 else 'Bearish' if d_now==-1 else 'No clear bias'} on 4H/1H"),
    gs("phase", "Pullback phase (not mid-push)", "pass" if phase_ok else ("na" if not d_now else "fail"),
       f"Price {'below' if C[i] < ema else 'above'} 4H 10-EMA" if d_now else "—"),
    gs("poi", "Price AT strong 4H POI",
       "pass" if (poi_info and poi_info["at_zone"]) else ("fail" if poi_info else "na"),
       (f"Zone {poi_info['zlo']}–{poi_info['zhi']} ({poi_info['dist_atr']} ATR away)" if poi_info
        else "No live zone in trend direction")),
    gs("inducement", "Inducement identified",
       "pass" if st in (1,2,3,4) else ("wait" if st == 5 else "na"),
       stage_detail if st == 5 else ("Marked" if st in (1,2,3,4) else "—")),
    gs("sweep", "V-shape liquidity sweep",
       "pass" if st in (2,3,4) else ("wait" if st == 1 else "na"),
       stage_detail if st in (1,2,3) else ("Done" if st == 4 else "—")),
    gs("shift", "Market shift",
       "pass" if st == 4 else ("wait" if st == 3 else "na"),
       "Confirmed — flip zone armed" if st == 4 else ("Waiting for takeout" if st == 3 else "—")),
    gs("flip", "S/D flip + retrace to OB/flip zone", "wait" if st == 4 else "na",
       stage_detail if st == 4 else "—"),
    gs("momentum", "Momentum confirmation at zone", "wait" if st == 4 else "na",
       "Waiting for momentum candle overlapping the zone" if st == 4 else "—"),
]

fresh = [s for s in sims
         if (T[-1] - pd.Timestamp(s["time"])).total_seconds() < 3*3600]
verdict, levels = "NO TRADE", None
reason = "Waiting for: " + STAGE_WAIT.get(st, "setup")
if fresh:
    f = fresh[-1]
    if f["result"] == "open":
        verdict, levels = "TRADE", {"dir": f["dir"], "entry": f["entry"],
                                    "sl": f["sl"], "tp": f["tp"]}
        reason = f"All gates passed at {f['time']}"
    else:
        reason = (f"Last signal {f['time']} resolved ({f['result']}, {f['r']:+.2f}R). "
                  + reason)

out = {"market": symbol, "data_asof": str(T[-1]), "price": round(float(C[-1]), 4),
       "verdict": verdict, "reason": reason, "levels": levels, "gates": gates,
       "stage": st, "recent_signals": sims[-8:][::-1]}
print(json.dumps(out))
