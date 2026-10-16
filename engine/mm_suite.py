"""
10 mechanical strategies, ALL derived from the Market Mechanics mentorship
(Brad Goh / The Trading Geek) concepts. BTC 1H entries, 4H bias.
Common: 1% risk/trade, 0.05%/side fee, one position at a time, all hours.

 1. mm_conservative : sweep -> market shift -> pullback to shift OB (Ep 18)
 2. mm_aggressive   : sweep -> immediate entry at sweep close (Ep 18)
 3. shift_pullback   : HTF bias + LTF shift -> pullback to OB, no sweep needed
 4. flip_retest      : broken S/D level retested from other side (Ep 14)
 5. premium_discount : premium->shorts / discount->longs + LTF shift (Ep 8)
 6. fvg_fill         : HTF bias + 50% fill of FVG (Ep 9)
 7. ob_touch         : HTF bias + mitigation of order block (Ep 10)
 8. sweep_reversal   : pure sweep of PDH/PDL/swing -> immediate reversal
 9. bos_continuation : HTF bias + LTF BOS -> pullback to breaker zone
10. eqhl_sweep       : sweep of EQUAL highs/lows (stop-loss pools, Ep 13)
"""
import numpy as np
import os
import pandas as pd

FEE = float(os.environ.get("FEE", "0.0005"))
DATA1H = os.environ.get("DATA1H", "/home/hatch/workspace/backtest/btc_1h.parquet")
DATA4H = os.environ.get("DATA4H", "/home/hatch/workspace/backtest/btc_4h.parquet")
h1 = pd.read_parquet(DATA1H)
h4 = pd.read_parquet(DATA4H)
h1.index = h1.index.tz_convert("UTC")
h4.index = h4.index.tz_convert("UTC")

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

h1["atr"] = atr(h1)
N = len(h1)
O = h1["open"].to_numpy(); H = h1["high"].to_numpy()
L = h1["low"].to_numpy(); C = h1["close"].to_numpy()
ATR = h1["atr"].to_numpy()
h4_pos = h4.index.searchsorted(h1.index, side="right") - 1

def swings(vals_h, vals_l, k):
    out = []
    for i in range(k, len(vals_h) - k):
        if vals_h[i] > vals_h[i-k:i].max() and vals_h[i] > vals_h[i+1:i+k+1].max():
            out.append((i + k, vals_h[i], "H"))
        if vals_l[i] < vals_l[i-k:i].min() and vals_l[i] < vals_l[i+1:i+k+1].min():
            out.append((i + k, vals_l[i], "L"))
    return out

SW3 = swings(H, L, 3)          # minor 1H swings (pools)
SW6 = swings(H, L, 6)          # significant 1H levels (flips)
SW4 = swings(h4["high"].to_numpy(), h4["low"].to_numpy(), 8)  # major 4H
LOW3 = [(p, px) for (p, px, kd) in SW3 if kd == "L"]
HIGH3 = [(p, px) for (p, px, kd) in SW3 if kd == "H"]

# equal highs/lows: pairs of minor swings within 0.15*ATR and 96 bars (Ep 13 pools)
day = pd.Series(h1.index.date, index=h1.index)
EQS = []  # (confirm_bar, level, dir)  dir=+1 -> sweep lows for long
for arr, d in ((HIGH3, -1), (LOW3, 1)):
    for n in range(len(arr)):
        p1, x1 = arr[n]
        for m in range(n + 1, len(arr)):
            p2, x2 = arr[m]
            if p2 - p1 > 96:
                break
            if not np.isnan(ATR[p2]) and abs(x1 - x2) <= 0.15 * ATR[p2]:
                EQS.append((p2, max(x1, x2) if d == -1 else min(x1, x2), d))
PDH = h1.groupby(day)["high"].transform("max").shift(24).to_numpy()
PDL = h1.groupby(day)["low"].transform("min").shift(24).to_numpy()

def htf_bias(i):
    i4 = h4_pos[i]
    s4 = [s for s in SW4 if s[0] <= i4]
    if len(s4) < 4:
        return None
    highs = [s for s in s4 if s[2] == "H"]; lows = [s for s in s4 if s[2] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    rng_hi, rng_lo = highs[-1][1], lows[-1][1]
    if rng_hi <= rng_lo:
        return None
    disc = (h4["close"].to_numpy()[i4] - rng_lo) / (rng_hi - rng_lo)
    score = (1 if highs[-1][1] > highs[-2][1] else -1 if highs[-1][1] < highs[-2][1] else 0) + \
            (1 if lows[-1][1] > lows[-2][1] else -1 if lows[-1][1] < lows[-2][1] else 0)
    if score > 0 and disc < 0.5: return "bull"
    if score < 0 and disc > 0.5: return "bear"
    return None

def pd_position(i):
    """premium/discount location: 'premium' / 'discount' / None (Ep 8)."""
    i4 = h4_pos[i]
    s4 = [s for s in SW4 if s[0] <= i4]
    if len(s4) < 2: return None
    highs = [s for s in s4 if s[2] == "H"]; lows = [s for s in s4 if s[2] == "L"]
    if not highs or not lows: return None
    rng_hi, rng_lo = highs[-1][1], lows[-1][1]
    if rng_hi <= rng_lo: return None
    disc = (h4["close"].to_numpy()[i4] - rng_lo) / (rng_hi - rng_lo)
    if disc > 0.62: return "premium"
    if disc < 0.38: return "discount"
    return None

def htf_magnet(i, d, entry):
    i4 = h4_pos[i]
    s4 = [s for s in SW4 if s[0] <= i4]
    if d == 1:
        cands = [x for x in [PDH[i]] + [px for (p, px, kd) in s4 if kd == "H"]
                 if not np.isnan(x) and x > entry]
    else:
        cands = [x for x in [PDL[i]] + [px for (p, px, kd) in s4 if kd == "L"]
                 if not np.isnan(x) and x < entry]
    return min(cands, key=lambda x: abs(x - entry)) if cands else None

def last_minor(i, kind, cool, key):
    lst = LOW3 if kind == "L" else HIGH3
    for (p, px) in reversed(lst):
        if p <= i and cool.get((key, p), -1) <= i:
            return (p, px)
    return None

def origin_ob(shift_i, d):
    """Order block: last opposite candle before the shift (displacement origin)."""
    for b in range(shift_i, max(shift_i - 6, 0), -1):
        if (d == 1 and C[b] < O[b]) or (d == -1 and C[b] > O[b]):
            return L[b], H[b]
    return min(O[shift_i], C[shift_i]), max(O[shift_i], C[shift_i])

# ---------------- strategy scanners ----------------
# Each scanner is a generator-ish object with .scan(i) -> signal dict or None.
# Signal: {"dir", "entry", "sl", "tp", "min_rr"}

class S:
    def __init__(s): s.armed = None; s.cool = {}; s.flips = []
    def scan(s, i): return None

def mk_signal(d, entry, sl, tp, min_rr=0.8):
    if tp is None or abs(entry - sl) < 1e-9: return None
    if abs(entry - sl) < 0.0004 * entry: return None  # dust stop; playbook uses tight stops
    if abs(tp - entry) / abs(entry - sl) < min_rr: return None
    return {"dir": d, "entry": entry, "sl": sl, "tp": tp}

class Conservative(S):  # 1: sweep -> shift -> pullback to OB
    def scan(s, i):
        d8 = h1.index[i].date()
        if s.armed is None:
            bias = htf_bias(i)
            if bias is None or np.isnan(ATR[i]): return None
            d = 1 if bias == "bull" else -1
            fl = last_minor(i, "L" if d == 1 else "H", s.cool, "f")
            pools = []
            if fl: pools.append((("f", fl[0]), fl[1]))
            pools.append((("pd", d8), PDL[i] if d == 1 else PDH[i]))
            for pid, lvl in pools:
                if np.isnan(lvl): continue
                wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
                if ((L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)) \
                        and wick >= 0.10 * ATR[i]:
                    s.cool[pid] = i + 120
                    s.armed = {"dir": d, "sweep_i": i, "prot": L[i] if d == 1 else H[i],
                               "until": i + 48}
                    return None
            return None
        a, d = s.armed, s.armed["dir"]
        if i > a["until"]: s.armed = None; return None
        if (d == 1 and C[i] < a["prot"]) or (d == -1 and C[i] > a["prot"]):
            s.armed = None; return None
        if "zone" not in a:
            lo = max(0, a["sweep_i"] - 5)
            lvl = H[lo:a["sweep_i"] + 1].max() if d == 1 else L[lo:a["sweep_i"] + 1].min()
            if (d == 1 and C[i] > lvl) or (d == -1 and C[i] < lvl):
                zlo, zhi = origin_ob(i, d)
                a.update(zone=(zlo, zhi), fill_until=i + 12)
            return None
        if i > a["fill_until"]: s.armed = None; return None
        zlo, zhi = a["zone"]; mid = (zlo + zhi) / 2
        if H[i] >= mid >= L[i]:
            s.armed = None
            sl = a["prot"] - 0.1 * ATR[i] if d == 1 else a["prot"] + 0.1 * ATR[i]
            return mk_signal(d, mid, sl, htf_magnet(i, d, mid))
        return None

class Aggressive(S):  # 2: sweep -> enter at close
    def scan(s, i):
        d8 = h1.index[i].date()
        bias = htf_bias(i)
        if bias is None or np.isnan(ATR[i]): return None
        d = 1 if bias == "bull" else -1
        fl = last_minor(i, "L" if d == 1 else "H", s.cool, "f")
        pools = []
        if fl: pools.append((("f", fl[0]), fl[1]))
        pools.append((("pd", d8), PDL[i] if d == 1 else PDH[i]))
        for pid, lvl in pools:
            if np.isnan(lvl): continue
            wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
            if ((L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)) \
                    and wick >= 0.10 * ATR[i]:
                s.cool[pid] = i + 120
                sl = L[i] - 0.1 * ATR[i] if d == 1 else H[i] + 0.1 * ATR[i]
                return mk_signal(d, C[i], sl, htf_magnet(i, d, C[i]))
        return None

class ShiftPullback(S):  # 3: bias + shift -> pullback (no sweep)
    def scan(s, i):
        if s.armed is None:
            bias = htf_bias(i)
            if bias is None or np.isnan(ATR[i]): return None
            d = 1 if bias == "bull" else -1
            lo = max(0, i - 6)
            lvl = H[lo:i].max() if d == 1 else L[lo:i].min()  # prior bars only
            if (d == 1 and C[i] > lvl) or (d == -1 and C[i] < lvl):
                zlo, zhi = origin_ob(i, d)
                s.armed = {"dir": d, "prot": L[lo:i].min() if d == 1 else H[lo:i].max(),
                           "zone": (zlo, zhi), "fill_until": i + 12}
            return None
        a, d = s.armed, s.armed["dir"]
        if i > a["fill_until"]: s.armed = None; return None
        if (d == 1 and C[i] < a["prot"]) or (d == -1 and C[i] > a["prot"]):
            s.armed = None; return None
        zlo, zhi = a["zone"]; mid = (zlo + zhi) / 2
        if H[i] >= mid >= L[i]:
            s.armed = None
            return mk_signal(d, mid, a["prot"], htf_magnet(i, d, mid))
        return None

class FlipRetest(S):  # 4: broken S/D retested from other side (Ep 14)
    def __init__(s):
        super().__init__()
        s.ptr = 0; s.levels = []; s.seen = set()
    def scan(s, i):
        # feed newly confirmed significant levels; keep last 300 bars
        while s.ptr < len(SW6) and SW6[s.ptr][0] <= i:
            s.levels.append(SW6[s.ptr]); s.ptr += 1
        s.levels = [lv for lv in s.levels if i - lv[0] <= 300]
        # register closes THROUGH a level (break), not at confirmation time
        for (p, px, kd) in s.levels:
            if (p, px) in s.seen: continue
            if kd == "H" and C[i] > px and C[i - 1] <= px:
                s.seen.add((p, px))
                s.flips.append({"lvl": px, "dir": 1, "until": i + 24})
            elif kd == "L" and C[i] < px and C[i - 1] >= px:
                s.seen.add((p, px))
                s.flips.append({"lvl": px, "dir": -1, "until": i + 24})
        s.flips = [f for f in s.flips if f["until"] >= i]
        bias = htf_bias(i)
        if bias is None or np.isnan(ATR[i]): return None
        bd = 1 if bias == "bull" else -1
        for f in list(s.flips):
            if f["dir"] != bd: continue
            if L[i] <= f["lvl"] <= H[i]:
                # invalidation: acceptance back through the flipped level
                sl = f["lvl"] - 0.3 * ATR[i] if bd == 1 else f["lvl"] + 0.3 * ATR[i]
                s.flips.remove(f)
                return mk_signal(bd, f["lvl"], sl, htf_magnet(i, bd, f["lvl"]))
        return None

class PremiumDiscount(S):  # 5: location + shift (Ep 8)
    def scan(s, i):
        if s.armed is None:
            loc = pd_position(i)
            if loc is None or np.isnan(ATR[i]): return None
            d = -1 if loc == "premium" else 1
            lo = max(0, i - 6)
            lvl = H[lo:i].max() if d == 1 else L[lo:i].min()  # prior bars only
            if (d == 1 and C[i] > lvl) or (d == -1 and C[i] < lvl):
                zlo, zhi = origin_ob(i, d)
                s.armed = {"dir": d, "prot": L[lo:i].min() if d == 1 else H[lo:i].max(),
                           "zone": (zlo, zhi), "fill_until": i + 12}
            return None
        a, d = s.armed, s.armed["dir"]
        if i > a["fill_until"]: s.armed = None; return None
        if (d == 1 and C[i] < a["prot"]) or (d == -1 and C[i] > a["prot"]):
            s.armed = None; return None
        zlo, zhi = a["zone"]; mid = (zlo + zhi) / 2
        if H[i] >= mid >= L[i]:
            s.armed = None
            return mk_signal(d, mid, a["prot"], htf_magnet(i, d, mid))
        return None

class FvgFill(S):  # 6: 50% fill of FVG with HTF bias (Ep 9)
    def scan(s, i):
        if not hasattr(s, "fvgs"): s.fvgs = []
        if i >= 3 and not np.isnan(ATR[i]):
            if L[i] > H[i - 2]:  # bullish FVG
                s.fvgs.append({"glo": H[i - 2], "ghi": L[i], "dir": 1, "until": i + 48})
            elif H[i] < L[i - 2]:  # bearish FVG
                s.fvgs.append({"glo": H[i], "ghi": L[i - 2], "dir": -1, "until": i + 48})
        s.fvgs = [f for f in s.fvgs if f["until"] >= i]
        if np.isnan(ATR[i]): return None
        bias = htf_bias(i)
        if bias is None: return None
        bd = 1 if bias == "bull" else -1
        for f in list(s.fvgs):
            if f["dir"] != bd: continue
            mid = (f["glo"] + f["ghi"]) / 2
            if L[i] <= mid <= H[i]:
                s.fvgs.remove(f)
                sl = f["glo"] - 0.1 * ATR[i] if bd == 1 else f["ghi"] + 0.1 * ATR[i]
                return mk_signal(bd, mid, sl, htf_magnet(i, bd, mid))
        return None

class ObTouch(S):  # 7: mitigation of order block with HTF bias (Ep 10)
    def scan(s, i):
        if not hasattr(s, "obs"): s.obs = []
        if np.isnan(ATR[i]): return None
        # register displacement -> order block
        if i >= 10 and H[i] - L[i] >= 1.5 * ATR[i]:
            for d, kind in ((1, "H"), (-1, "L")):
                ref = last_minor(i - 1, kind, {}, "x")
                if ref is None: continue
                if (d == 1 and C[i] > ref[1]) or (d == -1 and C[i] < ref[1]):
                    for b in range(i - 1, max(i - 4, 0), -1):
                        if (d == 1 and C[b] < O[b]) or (d == -1 and C[b] > O[b]):
                            s.obs.append({"zlo": L[b], "zhi": H[b], "dir": d,
                                          "until": i + 48, "born": i})
                            break
        s.obs = [o for o in s.obs if o["until"] >= i]
        bias = htf_bias(i)
        if bias is None: return None
        bd = 1 if bias == "bull" else -1
        for o in list(s.obs):
            if o["dir"] != bd or o["born"] >= i: continue
            edge = o["zhi"] if bd == 1 else o["zlo"]
            if L[i] <= edge <= H[i]:
                s.obs.remove(o)
                sl = o["zlo"] - 0.1 * ATR[i] if bd == 1 else o["zhi"] + 0.1 * ATR[i]
                return mk_signal(bd, edge, sl, htf_magnet(i, bd, edge))
        return None

class SweepReversal(S):  # 8: pure sweep -> reversal, no POI needed
    def scan(s, i):
        d8 = h1.index[i].date()
        if np.isnan(ATR[i]): return None
        # both directions scanned; no HTF bias (pure liquidity grab fade)
        for d, lvl, pid in ((1, PDL[i], ("pdl", d8)), (-1, PDH[i], ("pdh", d8))):
            if np.isnan(lvl) or s.cool.get(pid, -1) > i: continue
            wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
            crossed = (L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)
            if crossed and wick >= 0.15 * ATR[i]:
                s.cool[pid] = i + 120
                sl = L[i] - 0.1 * ATR[i] if d == 1 else H[i] + 0.1 * ATR[i]
                return mk_signal(d, C[i], sl, htf_magnet(i, d, C[i]), min_rr=1.0)
        # minor swing sweeps
        for d, kind in ((1, "L"), (-1, "H")):
            fl = last_minor(i, kind, s.cool, "s")
            if fl is None: continue
            p, lvl = fl
            wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
            crossed = (L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)
            if crossed and wick >= 0.15 * ATR[i]:
                s.cool[("s", p)] = i + 120
                sl = L[i] - 0.1 * ATR[i] if d == 1 else H[i] + 0.1 * ATR[i]
                return mk_signal(d, C[i], sl, htf_magnet(i, d, C[i]), min_rr=1.0)
        return None

class BosContinuation(S):  # 9: HTF bias + LTF BOS -> pullback to breaker
    def scan(s, i):
        if s.armed is None:
            bias = htf_bias(i)
            if bias is None or np.isnan(ATR[i]): return None
            d = 1 if bias == "bull" else -1
            ref = last_minor(i - 1, "H" if d == 1 else "L", {}, "x")
            if ref is None: return None
            if (d == 1 and C[i] > ref[1]) or (d == -1 and C[i] < ref[1]):
                zlo, zhi = min(O[i], C[i]), max(O[i], C[i])
                s.armed = {"dir": d, "prot": L[i] if d == 1 else H[i],
                           "zone": (zlo, zhi), "fill_until": i + 12}
            return None
        a, d = s.armed, s.armed["dir"]
        if i > a["fill_until"]: s.armed = None; return None
        if (d == 1 and C[i] < a["prot"]) or (d == -1 and C[i] > a["prot"]):
            s.armed = None; return None
        zlo, zhi = a["zone"]; mid = (zlo + zhi) / 2
        if H[i] >= mid >= L[i]:
            s.armed = None
            return mk_signal(d, mid, a["prot"], htf_magnet(i, d, mid))
        return None

class EqSweep(S):  # 10: sweep of EQUAL highs/lows (Ep 13)
    def scan(s, i):
        if np.isnan(ATR[i]): return None
        for (p2, lvl, d) in EQS:
            if p2 > i or i - p2 > 96: continue
            pid = ("eq", p2, d)
            if s.cool.get(pid, -1) > i: continue
            wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
            crossed = (L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)
            if crossed and wick >= 0.10 * ATR[i]:
                s.cool[pid] = i + 240
                sl = L[i] - 0.1 * ATR[i] if d == 1 else H[i] + 0.1 * ATR[i]
                return mk_signal(d, C[i], sl, htf_magnet(i, d, C[i]), min_rr=1.0)
        return None

STRATS = [
    ("mm_conservative", Conservative),
    ("mm_aggressive", Aggressive),
    ("shift_pullback", ShiftPullback),
    ("flip_retest", FlipRetest),
    ("premium_discount", PremiumDiscount),
    ("fvg_fill", FvgFill),
    ("ob_touch", ObTouch),
    ("sweep_reversal", SweepReversal),
    ("bos_continuation", BosContinuation),
    ("eq_sweep", EqSweep),
]

# ---------------- driver ----------------
def run_backtest(name, cls):
    st = cls()
    equity = 10000.0
    pos = None
    trades = []
    curve = [equity]
    for i in range(200, N):
        if pos is not None:
            d = pos["dir"]
            sl_hit = L[i] <= pos["sl"] if d == 1 else H[i] >= pos["sl"]
            tp_hit = H[i] >= pos["tp"] if d == 1 else L[i] <= pos["tp"]
            if sl_hit or tp_hit:
                if sl_hit:
                    px, R = pos["sl"], -1.0
                else:
                    px = pos["tp"]
                    R = abs(px - pos["entry"]) / abs(pos["entry"] - pos["sl"])
                pnl = R * pos["risk"] - pos["units"] * px * FEE
                equity += pnl
                trades.append({"R": R, "pnl": pnl})
                pos = None
        if pos is None:
            sig = st.scan(i)
            if sig:
                risk = 0.01 * equity
                units = risk / abs(sig["entry"] - sig["sl"])
                if units * sig["entry"] > 10 * equity:
                    continue  # >10x leverage: unrealistic, skip
                equity -= units * sig["entry"] * FEE
                pos = {**sig, "risk": risk, "units": units}
        curve.append(equity)
    tr = pd.DataFrame(trades)
    curve = pd.Series(curve)
    res = {"name": name, "trades": len(tr), "end": equity,
           "return": equity / 10000 - 1,
           "maxDD": float((curve / curve.cummax() - 1).min())}
    if len(tr):
        res.update(win_rate=float((tr["R"] > 0).mean()), avg_R=float(tr["R"].mean()),
                   pf=float(tr.loc[tr.pnl > 0, "pnl"].sum() / max(-tr.loc[tr.pnl < 0, "pnl"].sum(), 1e-9)))
    curve.to_csv(f"/home/hatch/workspace/backtest/mm10_{name}.csv", index=False, header=["equity"])
    return res

if __name__ == "__main__":
    import json
    out = []
    for name, cls in STRATS:
        r = run_backtest(name, cls)
        out.append(r)
        print(f"{r['name']:16s} trades={r['trades']:4d} win={r.get('win_rate',0):.0%} "
              f"avgR={r.get('avg_R',0):+.2f} pf={r.get('pf',0):.2f} ret={r['return']:+.1%} dd={r['maxDD']:.1%}")
    with open("/home/hatch/workspace/backtest/mm10_results.json", "w") as f:
        json.dump(out, f, indent=1)
