"""
Playbook Signal Dashboard — Flask web service for Render.
Thin server: receives pre-computed signals from the scanner VM via
POST /api/ingest (shared-secret auth) and serves the dashboard.
Signal tool only — not financial advice, no auto-trading.
"""
import json, os, hmac
from datetime import datetime, timezone
from flask import Flask, jsonify, Response, request

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "signals_cache.json")
INGEST_SECRET = os.environ.get("INGEST_SECRET", "")

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
.disc{color:var(--mut);font-size:.78rem;margin-top:18px;line-height:1.5;border-top:1px solid #2a3550;padding-top:12px}
.stale{color:var(--red);font-weight:700}
</style></head><body>
<h1>📡 Playbook Signal Dashboard</h1>
<div class="sub">Mechanical playbook (Market Mechanics framework) — gate checklist per market.
<span id="upd"></span> <span id="stale"></span></div>
<div class="tabs" id="tabs"></div>
<div id="main"><p class="sub">Loading…</p></div>
<div class="disc">Signal tool only — not financial advice. Backtested expectancy is historical (BTC 57% win @1:2R,
EURUSD 1 trade, gold-scalp 33%/0%); no win rate is guaranteed. Fixed 1% risk per trade; every gate must pass or the
verdict is NO TRADE. Signals computed hourly by the scanner engine.</div>
<script>
let DATA=null, CUR=null;
const B={pass:'PASS',fail:'FAIL',wait:'WAIT',na:'—'};
async function load(){
  const r=await fetch('/api/signals'); DATA=await r.json(); render();
}
function render(){
  const ms=DATA.markets||{}, names=Object.keys(ms).filter(n=>n!=='__ACCOUNT__');
  const acct=(ms['__ACCOUNT__']||{}).account||{};
  if(!names.length){document.getElementById('main').innerHTML='<p class="sub">No signal data yet — scanner updating…</p>';return;}
  if(!CUR||!ms[CUR]) CUR=names[0];
  const upd=DATA.updated?new Date(DATA.updated):null;
  document.getElementById('upd').textContent=upd?('Updated '+upd.toLocaleString()):'';
  const ageH=upd?(Date.now()-upd.getTime())/36e5:null;
  document.getElementById('stale').innerHTML=(ageH!==null&&ageH>3)?'<span class="stale">STALE ('+ageH.toFixed(1)+'h old)</span>':'';
  document.getElementById('tabs').innerHTML=names.map(n=>{
    const m=ms[n], v=m.verdict||'ERR';
    return `<button class="tab${n===CUR?' on':''}" onclick="CUR='${n}';render()">${n} · ${v==='TRADE'?'🟢':v==='NO TRADE'?'🟡':'🔴'}</button>`}).join('');
  const m=ms[CUR];
  if(m.error){document.getElementById('main').innerHTML=`<div class="card" style="color:var(--red)">Error: ${m.error}</div>`;return;}
  const vc=m.verdict==='TRADE'?'v-trade':'v-no';
  let h=`<div class="card"><span class="verdict ${vc}">${m.verdict}</span>
    <p style="margin:10px 0 0">${m.reason||''}</p>
    <p class="sub" style="margin:6px 0 0">${m.name} · ${m.price} · data as of ${m.data_asof}</p>`;
  if(m.levels){const L=m.levels;
    h+=`<div class="lv"><div><small>Direction</small><b>${L.dir}</b></div><div><small>Entry</small><b>${L.entry}</b></div><div><small>Stop</small><b style="color:var(--red)">${L.sl}</b></div><div><small>Target (1:2R)</small><b style="color:var(--grn)">${L.tp}</b></div></div>`;}
  h+=`</div><div class="card"><h2>Gate checklist</h2>`+
    (m.gates||[]).map(g=>`<div class="gate"><span>${g.name}<br><small style="color:var(--mut)">${g.detail||''}</small></span><span class="badge ${g.state}">${B[g.state]||g.state}</span></div>`).join('')+`</div>`;
  h+=`<div class="card"><h2>Recent signals</h2><table><tr><th>Time</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th><th>Result</th><th>R</th></tr>`+
    (m.recent_signals||[]).map(s=>`<tr><td>${(s.time||'').slice(0,16).replace('T',' ')}</td><td>${s.dir}</td><td>${s.entry}</td><td>${s.sl}</td><td>${s.tp}</td><td class="${s.result==='tp'?'win':s.result==='sl'?'loss':''}">${(s.result||'').toUpperCase()}</td><td class="${s.r>0?'win':s.r<0?'loss':''}">${s.r>0?'+':''}${s.r}R</td></tr>`).join('')+`</table></div>`;
  const bt=m.backtest;
  if(bt&&bt.trades!==undefined){h+=`<div class="card"><h2>Backtest (fixed 1:2R)</h2><p class="sub">${bt.trades} trades · ${(bt.win*100).toFixed(0)}% win · ${bt.avgR>=0?'+':''}${bt.avgR}R avg · ${bt.ret>=0?'+':''}${bt.ret}% return</p></div>`;}
  // account panel
  const an=Object.keys(acct);
  if(an.length){h+=`<div class="card"><h2>💰 Connected accounts</h2>`+an.map(k=>{
    const a=acct[k], b=a.balance||{}, ps=a.positions||[];
    const poss=Array.isArray(ps)?ps.map(p=>`${p.symbol} ${p.side} ${p.qty} @ ${p.entry} (P&amp;L ${p.pnl})`).join('<br>'):(ps.error||'—');
    return `<p><b>${k}</b> — balance $${b.total_usd??'—'}`+
      (b.cash!==undefined?` (cash $${b.cash})`:'')+
      `<br><small style="color:var(--mut)">Positions (${Array.isArray(ps)?ps.length:0}):</small><br>${poss||'none'}</p>`;
  }).join('')+`</div>`;}
  document.getElementById('main').innerHTML=h;
}
load(); setInterval(load, 5*60*1000);
</script></body></html>"""

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/api/signals")
def api_signals():
    return jsonify(_cache)

@app.route("/api/ingest", methods=["POST", "GET"])
def api_ingest():
    global _cache
    if request.method == "GET":
        # GET fallback: VM egress blocks POST; send one market per GET
        # /api/ingest?secret=...&market=BTC&data=<urlencoded json>
        if request.args.get("secret", "") != INGEST_SECRET or not INGEST_SECRET:
            return jsonify({"error": "unauthorized"}), 401
        name = request.args.get("market", "")
        raw = request.args.get("data", "")
        if not name or not raw:
            return jsonify({"error": "empty"}), 400
        try:
            m = json.loads(raw)
        except Exception as e:
            return jsonify({"error": "bad json"}), 400
        _cache["markets"][name] = m
        _cache["updated"] = datetime.now(timezone.utc).isoformat()
        save_cache(_cache)
        return jsonify({"ok": True, "market": name})
    auth = request.headers.get("Authorization", "")
    if not INGEST_SECRET or not hmac.compare_digest(auth, "Bearer " + INGEST_SECRET):
        return jsonify({"error": "unauthorized"}), 401
    try:
        payload = request.get_json(force=True)
        markets = payload.get("markets", {})
        if not markets:
            return jsonify({"error": "empty"}), 400
        _cache = {"updated": datetime.now(timezone.utc).isoformat(),
                  "markets": markets}
        save_cache(_cache)
        return jsonify({"ok": True, "markets": len(markets)})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 400

@app.route("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
