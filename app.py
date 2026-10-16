"""
Playbook Signal Dashboard — Flask web service for Render.
Serves the mechanical playbook (Brad Goh / The Trading Geek framework)
signal dashboard: per-market gate checklist, TRADE/NO TRADE verdict,
entry/SL/TP levels, recent signal history.
Signal tool only — not financial advice, no auto-trading.
"""
import json, os, subprocess, sys, threading, time
from datetime import datetime, timezone
from flask import Flask, jsonify, Response

BASE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(BASE, "engine", "worker.py")
CACHE = os.path.join(BASE, "signals_cache.json")
PY = sys.executable

MARKETS = [
    ("BTC", "BTC-USD"), ("ETH", "ETH-USD"), ("GOLD", "GC=F"),
    ("EURUSD", "EURUSD=X"), ("GBPUSD", "GBPUSD=X"), ("GBPJPY", "GBPJPY=X"),
]
STALE_SECS = 3600
_refresh_lock = threading.Lock()
_cache = {"updated": None, "markets": {}}

def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE))
        except Exception:
            pass
    return {"updated": None, "markets": {}}

def save_cache(d):
    try:
        json.dump(d, open(CACHE, "w"))
    except Exception:
        pass

_cache.update(load_cache())

def run_worker(ticker):
    try:
        p = subprocess.run([PY, ENGINE, ticker], capture_output=True,
                           text=True, timeout=900)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"market": ticker, "error": str(e)[:200]}

def refresh(force=False):
    global _cache
    with _refresh_lock:
        upd = _cache.get("updated")
        if not force and upd:
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(upd)).total_seconds()
                if age < STALE_SECS:
                    return _cache
            except Exception:
                pass
        markets = {}
        for name, ticker in MARKETS:
            r = run_worker(ticker)
            r["name"] = name
            markets[name] = r
        _cache = {"updated": datetime.now(timezone.utc).isoformat(),
                  "markets": markets}
        save_cache(_cache)
        return _cache

app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Playbook Signal Dashboard</title>
<style>
:root{--bg:#0f1420;--card:#1a2233;--txt:#e8edf5;--mut:#8b96ab;--grn:#22c55e;--red:#ef4444;--amb:#f59e0b;--acc:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,sans-serif;padding:16px;max-width:1100px;margin:auto}
h1{font-size:1.4rem;margin:8px 0}h2{font-size:1.05rem;margin:14px 0 8px}
.sub{color:var(--mut);font-size:.85rem;margin-bottom:12px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.tab{padding:8px 14px;border-radius:8px;background:var(--card);border:1px solid #2a3550;cursor:pointer;color:var(--txt)}
.tab.on{border-color:var(--acc);background:#16283a}
.card{background:var(--card);border:1px solid #2a3550;border-radius:12px;padding:14px;margin:10px 0}
.verdict{font-size:1.3rem;font-weight:700;padding:10px 16px;border-radius:10px;display:inline-block}
.v-trade{background:#052e1b;color:var(--grn);border:1px solid var(--grn)}
.v-no{background:#2b1a05;color:var(--amb);border:1px solid var(--amb)}
.lv{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
.lv div{background:#0f1729;padding:10px 14px;border-radius:8px;min-width:110px}
.lv small{color:var(--mut);display:block}.lv b{font-size:1.05rem}
.gate{display:flex;justify-content:space-between;gap:10px;padding:8px 4px;border-bottom:1px solid #24304a;font-size:.92rem}
.badge{padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:600;white-space:nowrap}
.pass{background:#052e1b;color:var(--grn)}.fail{background:#3a0d0d;color:var(--red)}
.wait{background:#2b1a05;color:var(--amb)}.na{background:#222b40;color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{padding:8px 6px;border-bottom:1px solid #24304a;text-align:left}
th{color:var(--mut);font-weight:600}.win{color:var(--grn)}.loss{color:var(--red)}
.btn{background:var(--acc);color:#04263b;border:0;padding:9px 18px;border-radius:8px;font-weight:700;cursor:pointer}
.disc{color:var(--mut);font-size:.78rem;margin-top:18px;line-height:1.5;border-top:1px solid #2a3550;padding-top:12px}
.err{color:var(--red)}
</style></head><body>
<h1>📡 Playbook Signal Dashboard</h1>
<div class="sub">Mechanical playbook (Market Mechanics framework) — gate checklist per market.
<span id="upd"></span></div>
<div class="tabs" id="tabs"></div>
<div id="main"><p class="sub">Loading…</p></div>
<div style="margin:14px 0"><button class="btn" onclick="refresh(true)">↻ Refresh signals</button></div>
<div class="disc">Signal tool only — not financial advice. Backtested expectancy is historical (BTC 57% win @1:2R,
EURUSD 1 trade, gold-scalp 33%/0%); no win rate is guaranteed. Fixed 1% risk per trade; every gate must pass or the
verdict is NO TRADE. Data: Yahoo Finance 1H (≈2y) → 4H resample.</div>
<script>
let DATA=null, CUR=null;
const B={pass:'PASS',fail:'FAIL',wait:'WAIT',na:'—'};
async function load(force){
  document.getElementById('main').innerHTML='<p class="sub">Scanning markets… (up to a minute)</p>';
  const r=await fetch('/api/signals'+(force?'?force=1':'')); DATA=await r.json(); render();
}
function render(){
  const ms=DATA.markets, names=Object.keys(ms);
  if(!CUR||!ms[CUR]) CUR=names[0];
  document.getElementById('upd').textContent='Updated '+new Date(DATA.updated).toLocaleString();
  document.getElementById('tabs').innerHTML=names.map(n=>{
    const m=ms[n], v=m.verdict||'ERR';
    return `<button class="tab${n===CUR?' on':''}" onclick="CUR='${n}';render()">${n} · ${v==='TRADE'?'🟢':v==='NO TRADE'?'🟡':'🔴'}</button>`}).join('');
  const m=ms[CUR];
  if(m.error){document.getElementById('main').innerHTML=`<div class="card err">Error: ${m.error}</div>`;return;}
  const vc=m.verdict==='TRADE'?'v-trade':'v-no';
  let h=`<div class="card"><span class="verdict ${vc}">${m.verdict}</span>
    <p style="margin:10px 0 0">${m.reason||''}</p>
    <p class="sub" style="margin:6px 0 0">${m.name} · ${m.price} · data as of ${m.data_asof}</p>`;
  if(m.levels){const L=m.levels;
    h+=`<div class="lv"><div><small>Direction</small><b>${L.dir}</b></div><div><small>Entry</small><b>${L.entry}</b></div><div><small>Stop</small><b style="color:var(--red)">${L.sl}</b></div><div><small>Target (1:2R)</small><b style="color:var(--grn)">${L.tp}</b></div></div>`;}
  h+=`</div><div class="card"><h2>Gate checklist</h2>`+
    m.gates.map(g=>`<div class="gate"><span>${g.name}<br><small style="color:var(--mut)">${g.detail||''}</small></span><span class="badge ${g.state}">${B[g.state]||g.state}</span></div>`).join('')+`</div>`;
  h+=`<div class="card"><h2>Recent signals</h2><table><tr><th>Time</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Result</th><th>R</th></tr>`+
    (m.recent_signals||[]).map(s=>`<tr><td>${s.time.slice(0,16).replace('T',' ')}</td><td>${s.dir}</td><td>${s.entry}</td><td>${s.sl}</td><td>${s.tp}</td><td class="${s.result==='tp'?'win':s.result==='sl'?'loss':''}">${s.result.toUpperCase()}</td><td class="${s.r>0?'win':s.r<0?'loss':''}">${s.r>0?'+':''}${s.r}R</td></tr>`).join('')+`</table></div>`;
  document.getElementById('main').innerHTML=h;
}
function refresh(f){load(f)}
load(false);
</script></body></html>"""

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/api/signals")
def api_signals():
    from flask import request
    force = request.args.get("force") == "1"
    # refresh in background on first cold call to avoid gateway timeouts
    if force or not _cache.get("updated"):
        t = threading.Thread(target=refresh, kwargs={"force": force}, daemon=True)
        t.start()
        t.join(timeout=1500)
    else:
        threading.Thread(target=refresh, daemon=True).start()
    return jsonify(_cache)

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    threading.Thread(target=refresh, kwargs={"force": True}, daemon=True).start()
    return jsonify({"status": "refreshing"})

@app.route("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
