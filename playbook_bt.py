"""
Backtest of the USER'S playbook (mechanical translation), BTC 1H, ~2y.
Playbook: HTF trend -> push/pullback phase -> price AT 4H POI (strong S&D/OB)
  -> inducement -> V-shape liquidity sweep -> market shift
  -> retrace to OB/flip zone + MOMENTUM -> enter
  SL: tight, just beyond flip zone (5-10 pips -> 0.1*ATR buffer on BTC)
  TP: distal of previous 1H swing high/low
1% risk/trade, 0.05%/side fee, one position at a time.
"""
import numpy as np
import pandas as pd
import mm_suite as M

h1, h4 = M.h1, M.h4
N = M.N
O, H, L, C, ATR = M.O, M.H, M.L, M.C, M.ATR
h4_pos = M.h4_pos

# ---- 4H POIs: demand/supply zones at origin of 4H displacements ----
H4 = h4["high"].to_numpy(); L4 = h4["low"].to_numpy()
C4 = h4["close"].to_numpy(); O4 = h4["open"].to_numpy()
tr4 = pd.concat([h4["high"] - h4["low"], (h4["high"] - h4["close"].shift()).abs(),
                 (h4["low"] - h4["close"].shift()).abs()], axis=1).max(axis=1)
ATR4 = tr4.rolling(14).mean().to_numpy()
SW4m = M.swings(H4, L4, 3)
POIS = []  # (bar4, zlo, zhi, dir)
for j in range(20, len(h4)):
    if np.isnan(ATR4[j]) or H4[j] - L4[j] < 1.5 * ATR4[j]:
        continue
    bull = C4[j] > O4[j]
    # must break a minor 4H swing to qualify as "strong"
    ref = next(((p, px, kd) for (p, px, kd) in reversed(SW4m) if p <= j - 1), None)
    if ref is None:
        continue
    if bull and not (C4[j] > ref[1] and ref[2] == "H"):
        continue
    if not bull and not (C4[j] < ref[1] and ref[2] == "L"):
        continue
    d = 1 if bull else -1
    zb = None
    for b in range(j - 1, max(j - 4, 0), -1):
        if (d == 1 and C4[b] < O4[b]) or (d == -1 and C4[b] > O4[b]):
            zb = b
            break
    if zb is None:
        zlo, zhi = (L4[j], (O4[j] + C4[j]) / 2) if d == 1 else ((O4[j] + C4[j]) / 2, H4[j])
    else:
        zlo, zhi = L4[zb], H4[zb]
    POIS.append((j, zlo, zhi, d))
print(f"4H POIs: {len(POIS)}")

# 4H 10-EMA for push/pullback phase
EMA4_10 = h4["close"].ewm(span=10, adjust=False).mean().to_numpy()

DIAG = dict(trend=0, phase=0, poi=0, inducement=0, sweep=0, vshape=0,
            shift=0, flip=0, retrace=0, momentum=0, rr_reject=0)

class Playbook(M.S):
    def scan(s, i):
        if np.isnan(ATR[i]) or i < 50:
            return None
        i4 = h4_pos[i]
        d = None
        st = s.__dict__.get("st", 0)

        # ---- stage 0: HTF trend + push/pullback phase + price AT 4H POI ----
        if st == 0:
            bias = M.htf_bias(i)
            if bias is None:
                return None
            d = 1 if bias == "bull" else -1
            DIAG["trend"] += 1
            # phase: pullback = price on the discount side of the 4H 10-EMA
            # (the setup is a pullback-into-POI reversal; push-phase not traded)
            ema = EMA4_10[i4]
            if not ((d == 1 and C[i] < ema) or (d == -1 and C[i] > ema)):
                return None
            DIAG["phase"] += 1
            # price AT a 4H POI: directional touch of a live strong S&D / OB zone
            #  long: dipped INTO demand (recent low at/under zone top)
            # short: rallied INTO supply (recent high at/over zone bottom)
            poi = None
            for (jb, zlo, zhi, pd) in reversed(POIS):
                if pd != d:
                    continue
                age_1h = i - jb * 4
                if age_1h < 0 or age_1h > 240:  # ~10 days
                    continue
                if d == 1 and min(L[max(0, i - 4):i + 1]) <= zhi + 0.2 * ATR[i]:
                    poi = (zlo, zhi)
                    break
                if d == -1 and max(H[max(0, i - 4):i + 1]) >= zlo - 0.2 * ATR[i]:
                    poi = (zlo, zhi)
                    break
            if poi is None:
                return None
            DIAG["poi"] += 1
            s.__dict__.update(st=5, d=d, poi_bar=i)  # st 5: wait for inducement to FORM
            return None

        # ---- stage 5: inducement forms while price sits at the POI ----
        if st == 5:
            d = s.__dict__["d"]
            if i - s.__dict__["poi_bar"] > 72:  # ~3 days, no inducement -> reset
                s.__dict__["st"] = 0
                return None
            lo = max(0, i - 12)
            rh, rl = H[lo:i + 1].max(), L[lo:i + 1].min()
            pool = None
            if rh - rl < 1.0 * ATR[i]:  # tight-range inducement
                pool = rl if d == 1 else rh
            else:  # equal highs/lows inducement
                for (p2, lvl, dd) in M.EQS:
                    if dd == d and 0 <= i - p2 <= 24:
                        pool = lvl
                        break
            if pool is None or np.isnan(pool):
                return None
            DIAG["inducement"] += 1
            s.__dict__.update(st=1, pool=pool, st0_bar=i)
            return None

        d = s.__dict__["d"]
        # ---- stage 1: V-shape liquidity sweep of the inducement extreme ----
        if st == 1:
            lvl = s.__dict__["pool"]
            wick = (lvl - L[i]) if d == 1 else (H[i] - lvl)
            crossed = (L[i] < lvl and C[i] > lvl) if d == 1 else (H[i] > lvl and C[i] < lvl)
            if crossed and wick >= 0.10 * ATR[i]:
                s.__dict__.update(st=2, sweep_i=i, prot=L[i] if d == 1 else H[i],
                                  v_until=i + 3)
                DIAG["sweep"] += 1
                return None
            if i - s.__dict__["st0_bar"] > 48:  # inducement went stale
                s.__dict__["st"] = 0
            return None

        # ---- stage 2: V confirmation (sharp reversal off the extreme) ----
        if st == 2:
            import os as _os2
            if _os2.environ.get("SKIP_V") == "1":
                DIAG["vshape"] += 1
                s.__dict__.update(st=3, shift_until=i + 48)
                return None
            if i > s.__dict__["v_until"]:
                s.__dict__["st"] = 0
                return None
            ext = s.__dict__["prot"]
            fav = (H[i] - ext) if d == 1 else (ext - L[i])
            if fav >= 0.5 * ATR[i]:
                DIAG["vshape"] += 1
                s.__dict__.update(st=3, shift_until=i + 48)
            return None

        # ---- stage 3: market shift ----
        # The shift FLIPS the broken internal level: broken resistance -> support
        # (the "Supply Demand Flip" checklist item). Entry zone = flip zone
        # around the broken level, or the origin OB ("OB/Flip Zone").
        if st == 3:
            if i > s.__dict__["shift_until"]:
                s.__dict__["st"] = 0
                return None
            if (d == 1 and C[i] < s.__dict__["prot"]) or (d == -1 and C[i] > s.__dict__["prot"]):
                s.__dict__["st"] = 0
                return None
            lo = max(0, s.__dict__["sweep_i"] - 5)
            lvl = H[lo:s.__dict__["sweep_i"] + 1].max() if d == 1 else L[lo:s.__dict__["sweep_i"] + 1].min()
            if (d == 1 and C[i] > lvl) or (d == -1 and C[i] < lvl):
                zlo, zhi = M.origin_ob(i, d)
                fz = 0.2 * ATR[i]
                flip = (lvl - fz, lvl + fz)  # flipped S/D zone around broken level
                s.__dict__.update(st=4, zones=[flip, (zlo, zhi)],
                                  fill_until=i + 12, shift_bar=i)
                DIAG["shift"] += 1
                DIAG["flip"] += 1
            return None

        # ---- stage 4: retrace to OB/flip zone + momentum -> enter ----
        # Per the playbook the momentum must fire AT the zone: entry stays close
        # to the flip zone so the 5-10 pip stop gives good R:R.
        if st == 4:
            if i > s.__dict__["fill_until"] or i - s.__dict__.get("shift_bar", i) > 30:
                s.__dict__["st"] = 0
                return None
            hit = None
            for (zlo, zhi) in s.__dict__["zones"]:
                mid = (zlo + zhi) / 2
                if L[i] <= mid <= H[i]:
                    hit = (zlo, zhi)
                    break
            if hit is None:
                if s.__dict__.get("touched"):
                    s.__dict__["st"] = 0  # left the zones without momentum -> reset
                return None
            zlo, zhi = hit
            DIAG["retrace"] += 1
            s.__dict__["touched"] = True
            # momentum AT the zone: big candle closing in trade direction,
            # still overlapping the zone (hasn't run away)
            import os as _os
            mom_mult = float(_os.environ.get("MOM_MULT", "1.0"))
            mom = (H[i] - L[i]) >= mom_mult * ATR[i] and \
                  ((d == 1 and C[i] > O[i] and C[i] > C[i - 1]) or
                   (d == -1 and C[i] < O[i] and C[i] < C[i - 1]))
            if mom:
                DIAG["momentum"] += 1
                s.__dict__["st"] = 0
                entry = C[i]
                # SL: 5-10 pips above/below flip zone -> 0.1*ATR or 7-pip
                # equivalent, whichever is larger (faithful on FX)
                buf = max(0.1 * ATR[i], 0.00065 * entry)
                sl = zlo - buf if d == 1 else zhi + buf
                import os
                rr_mult = float(os.environ.get("TP_RR", "0"))
                if rr_mult > 0:
                    tp = entry + d * rr_mult * abs(entry - sl)  # fixed R:R target
                elif os.environ.get("TP4H") == "1":
                    tp = M.htf_magnet(i, d, entry)  # sensitivity: HTF liquidity magnet
                else:
                    # TP: distal of previous 1H swing high/low -> nearest SIGNIFICANT
                    # 1H swing extreme beyond entry
                    cands = [px for (p, px, kd) in M.SW6
                             if p <= i and ((d == 1 and kd == "H" and px > entry) or
                                            (d == -1 and kd == "L" and px < entry))]
                    if not cands:
                        return None
                    tp = min(cands, key=lambda x: abs(x - entry))
                sig = M.mk_signal(d, entry, sl, tp, min_rr=0.8)
                if sig is None:
                    DIAG["rr_reject"] += 1
                return sig
            # touched but no momentum yet: allow a couple more bars
            s.__dict__["fill_until"] = max(s.__dict__["fill_until"], i + 2)
            return None
        return None

if __name__ == "__main__":
    import json
    r = M.run_backtest("playbook", Playbook)
    print("DIAG:", DIAG)
    print(f"{r['name']:16s} trades={r['trades']:4d} win={r.get('win_rate',0):.0%} "
          f"avgR={r.get('avg_R',0):+.2f} pf={r.get('pf',0):.2f} ret={r['return']:+.1%} dd={r['maxDD']:.1%}")
    with open("/home/hatch/workspace/backtest/playbook_result.json", "w") as f:
        json.dump({"result": r, "diag": DIAG}, f, indent=1)
