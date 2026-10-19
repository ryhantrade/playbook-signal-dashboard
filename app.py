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

# --- Forex Factory calendar proxy (for TradeMind live news) ---
# Fetches forexfactory.com/calendar server-side (no CORS issue) and
# returns parsed events as JSON with CORS headers for the static app.
_ff_cache = {"fetched_at": None, "events": [], "error": None}
import re, time
try:
    from html import unescape as _unescape
except Exception:
    def _unescape(s): return s

def _fetch_ff_calendar():
    global _ff_cache
    now = time.time()
    # cache for 15 minutes
    if _ff_cache["fetched_at"] and now - _ff_cache["fetched_at"] < 900 and _ff_cache["events"]:
        return _ff_cache
    events = []
    err = None
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://www.forexfactory.com/calendar",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
        html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
        # Parse calendar rows
        row_re = re.compile(r'<tr[^>]*class="[^"]*calendar__row[^"]*"[^>]*>(.*?)</tr>', re.S)
        cell_re = re.compile(r'<td[^>]*class="[^"]*calendar__([a-z-]+)[^"]*"[^>]*>(.*?)</td>', re.S)
        span_re = re.compile(r'<span[^>]*>(.*?)</span>', re.S)
        tag_re = re.compile(r'<[^>]+>')
        cur_date = ""
        for rm in row_re.finditer(html):
            row = rm.group(1)
            cells = {}
            for cm in cell_re.finditer(row):
                cls, inner = cm.group(1), cm.group(2)
                # impact: icon class -> High/Medium/Low/Holiday
                if cls == "impact":
                    m = re.search(r'icon--ff-impact-([a-z]+)', inner)
                    cells["impact"] = {"red": "High", "ora": "Medium", "yel": "Low", "gra": "Holiday"}.get(m.group(1) if m else "", "")
                else:
                    sm = span_re.search(inner)
                    txt = sm.group(1) if sm else inner
                    txt = _unescape(tag_re.sub("", txt)).strip()
                    cells[cls] = txt
            if not cells.get("event"):
                continue
            if cells.get("date"):
                cur_date = cells["date"]
            events.append({
                "date": cur_date,
                "time": cells.get("time", ""),
                "currency": cells.get("currency", ""),
                "impact": cells.get("impact", ""),
                "event": cells.get("event", ""),
                "actual": cells.get("actual", ""),
                "forecast": cells.get("forecast", ""),
                "previous": cells.get("previous", ""),
            })
    except Exception as e:
        err = str(e)[:200]
    _ff_cache = {"fetched_at": now, "events": events, "error": err}
    return _ff_cache

@app.route("/api/forex-calendar")
def api_forex_calendar():
    d = _fetch_ff_calendar()
    resp = jsonify({
        "fetched_at": datetime.fromtimestamp(d["fetched_at"], tz=timezone.utc).isoformat() if d["fetched_at"] else None,
        "count": len(d["events"]),
        "events": d["events"],
        "error": d["error"],
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

# --- Broker connect / integration system (for TradeMind) ---
# Real account connections: Paper (built-in), cTrader (Open API),
# MT5 (credential vault, live sync via terminal bridge),
# FTMO + FundingPips (prop firms — connect through MT5 or cTrader).
# Credentials stored server-side only in broker_creds.json (0600).
# Secrets are NEVER returned to the frontend (keys/passwords masked).
BROKER_CREDS_FILE = os.path.join(BASE, "broker_creds.json")

# Supported broker types
BROKER_TYPES = ("paper", "ctrader", "mt5", "ftmo", "fundingpips")
# Prop firms connect through a platform
PROP_PLATFORMS = ("mt5", "ctrader")

def _load_broker_creds():
    try:
        if os.path.exists(BROKER_CREDS_FILE):
            return json.load(open(BROKER_CREDS_FILE))
    except Exception:
        pass
    return {}

def _save_broker_creds(d):
    try:
        json.dump(d, open(BROKER_CREDS_FILE, "w"))
        os.chmod(BROKER_CREDS_FILE, 0o600)
    except Exception:
        pass

def _mask_key(k):
    k = k or ""
    if len(k) <= 8:
        return "***"
    return k[:4] + "..." + k[-4:]

def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

def _paper_balance():
    return {"total_usd": 10000.00, "cash": 10000.00, "open_positions": 0,
            "note": "Paper trading account — simulated $10,000"}

def _ctrader_validate(access_token, account_id=None, demo=True):
    """Validate a cTrader Open API access token via WebSocket (JSON).
    Returns (ok, balance_dict|error). Best-effort: connects, authenticates
    the trading account, and requests trader info for the balance.
    """
    try:
        import websocket as ws_client, json as _json, time as _time
        host = "wss://demo.ctrader.com:5036" if demo else "wss://live.ctrader.com:5035"
        # cTrader Open API also serves on openapi.ctrader.com; try primary then fallback
        hosts = [host, "wss://openapi.ctrader.com:5036" if demo else "wss://openapi.ctrader.com:5035"]
        last_err = ""
        for h in hosts:
            try:
                ws = ws_client.create_connection(h, timeout=12)
                break
            except Exception as e:
                last_err = str(e)[:120]
                ws = None
        if ws is None:
            return False, f"cTrader connection failed: {last_err}"
        try:
            # ProtoOAAccountAuthReq via JSON: payloadType 2102
            # ctidTraderAccountId is required; without it we can only do app-level calls.
            # We attempt account auth when account_id is given, else fall back to
            # a token-introspection style check via trader accounts lookup.
            if account_id:
                ws.send(_json.dumps({
                    "payloadType": 2102,
                    "payload": {"ctidTraderAccountId": int(account_id),
                                "accessToken": access_token},
                    "clientMsgId": "auth1"}))
            else:
                # Without account id, ask for the trader's accounts list is not
                # possible pre-auth; treat token as stored-but-unverified.
                ws.close()
                return True, {"total_usd": None, "note": "Token stored — open the Trading page to link an account ID for live balance."}
            deadline = _time.time() + 10
            authed = False
            balance = None
            while _time.time() < deadline:
                try:
                    ws.settimeout(max(1, deadline - _time.time()))
                    raw = ws.recv()
                except Exception:
                    break
                try:
                    msg = _json.loads(raw)
                except Exception:
                    continue
                pt = msg.get("payloadType")
                payload = msg.get("payload") or {}
                # 2103 = ProtoOAAccountAuthRes
                if pt == 2103:
                    authed = True
                    # request trader info: ProtoOATraderReq = 2104
                    ws.send(_json.dumps({"payloadType": 2104,
                                         "payload": {"ctidTraderAccountId": int(account_id)},
                                         "clientMsgId": "trader1"}))
                # 2105 = ProtoOATraderRes
                elif pt == 2105 and authed:
                    bal = payload.get("balance")
                    digits = payload.get("moneyDigits", 2)
                    if bal is not None:
                        try:
                            balance = float(bal) / (10 ** int(digits))
                        except Exception:
                            balance = None
                    break
                # 50 = ProtoOAErrorRes
                elif pt == 50:
                    desc = payload.get("description") or payload.get("errorCode") or "auth rejected"
                    ws.close()
                    return False, f"cTrader rejected the credentials: {str(desc)[:120]}"
            ws.close()
            if not authed:
                return False, "cTrader did not accept the access token (no auth response)."
            return True, {"total_usd": round(balance, 2) if balance is not None else None,
                          "account_id": str(account_id),
                          "note": "Live balance via cTrader Open API."}
        except Exception as e:
            try: ws.close()
            except Exception: pass
            return False, f"cTrader validation error: {str(e)[:150]}"
    except ImportError:
        return False, "cTrader validator unavailable on server."
    except Exception as e:
        return False, f"cTrader validation error: {str(e)[:150]}"

def _public_account(broker_key, creds):
    """Build the public (secret-free) account dict for one stored broker."""
    c = creds.get(broker_key, {})
    btype = c.get("type", broker_key)
    base = {"key": broker_key, "broker": btype,
            "label": c.get("label", broker_key),
            "connected_at": c.get("connected_at"),
            "platform": c.get("platform")}
    if btype == "paper":
        base["balance"] = _paper_balance()
    elif btype == "ctrader":
        base["key_masked"] = _mask_key(c.get("access_token", ""))
        base["account_id"] = c.get("account_id")
        base["demo"] = c.get("demo", True)
        bal = c.get("last_balance")
        base["balance"] = {"total_usd": bal, "note": "Live balance via cTrader Open API."} if bal is not None else {"total_usd": None, "note": "Token stored — balance refreshes on status check."}
    elif btype in ("mt5",):
        base["login_masked"] = _mask_key(c.get("login", ""))
        base["server"] = c.get("server", "")
        base["balance"] = {"total_usd": None, "note": "MT5 live sync needs the terminal bridge — credentials stored securely."}
    elif btype in ("ftmo", "fundingpips"):
        plat = c.get("platform", "mt5")
        base["platform"] = plat
        if plat == "ctrader":
            base["key_masked"] = _mask_key(c.get("access_token", ""))
            base["account_id"] = c.get("account_id")
        else:
            base["login_masked"] = _mask_key(c.get("login", ""))
            base["server"] = c.get("server", "")
        base["balance"] = {"total_usd": None, "note": f"{btype.upper()} via {plat.upper()} — credentials stored securely."}
    return base

@app.route("/api/broker/connect", methods=["POST", "OPTIONS"])
def api_broker_connect():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return _cors(jsonify({"ok": False, "error": "Invalid JSON body."})), 400
    broker = str(data.get("broker", "")).lower().strip()
    label = str(data.get("label", "") or broker).strip()[:60]
    if broker not in BROKER_TYPES:
        return _cors(jsonify({"ok": False, "error": f"Unsupported broker. Use one of: {', '.join(BROKER_TYPES)}."})), 400
    creds = _load_broker_creds()
    now = datetime.now(timezone.utc).isoformat()

    if broker == "paper":
        creds["paper"] = {"type": "paper", "label": label or "Paper Trading",
                          "connected_at": now}
        _save_broker_creds(creds)
        return _cors(jsonify({"ok": True, "account": _public_account("paper", creds)}))

    if broker == "ctrader":
        token = str(data.get("access_token", "")).strip()
        account_id = str(data.get("account_id", "")).strip()
        demo = bool(data.get("demo", True))
        if not token:
            return _cors(jsonify({"ok": False, "error": "cTrader access token is required."})), 400
        # Validate live against cTrader Open API when an account id is supplied;
        # otherwise store the token (user links the account id next).
        if account_id:
            ok, result = _ctrader_validate(token, account_id, demo)
            if not ok:
                return _cors(jsonify({"ok": False, "error": result})), 401
            last_bal = result.get("total_usd")
        else:
            last_bal = None
        creds["ctrader"] = {"type": "ctrader", "access_token": token,
                            "account_id": account_id or None, "demo": demo,
                            "last_balance": last_bal,
                            "label": label or "cTrader",
                            "connected_at": now}
        _save_broker_creds(creds)
        return _cors(jsonify({"ok": True, "account": _public_account("ctrader", creds)}))

    if broker == "mt5":
        login = str(data.get("login", "")).strip()
        password = str(data.get("password", ""))
        server = str(data.get("server", "")).strip()
        if not login or not password or not server:
            return _cors(jsonify({"ok": False, "error": "MT5 login, password and server are required."})), 400
        creds["mt5"] = {"type": "mt5", "login": login, "password": password,
                        "server": server, "label": label or "MetaTrader 5",
                        "connected_at": now}
        _save_broker_creds(creds)
        return _cors(jsonify({"ok": True, "account": _public_account("mt5", creds)}))

    if broker in ("ftmo", "fundingpips"):
        platform = str(data.get("platform", "mt5")).lower().strip()
        if platform not in PROP_PLATFORMS:
            return _cors(jsonify({"ok": False, "error": "Prop-firm platform must be 'mt5' or 'ctrader'."})), 400
        entry = {"type": broker, "platform": platform,
                 "label": label or broker.upper(), "connected_at": now}
        if platform == "ctrader":
            token = str(data.get("access_token", "")).strip()
            account_id = str(data.get("account_id", "")).strip()
            if not token:
                return _cors(jsonify({"ok": False, "error": "cTrader access token is required."})), 400
            if account_id:
                ok, result = _ctrader_validate(token, account_id, bool(data.get("demo", True)))
                if not ok:
                    return _cors(jsonify({"ok": False, "error": result})), 401
                entry["last_balance"] = result.get("total_usd")
            entry.update({"access_token": token, "account_id": account_id or None,
                          "demo": bool(data.get("demo", True))})
        else:
            login = str(data.get("login", "")).strip()
            password = str(data.get("password", ""))
            server = str(data.get("server", "")).strip()
            if not login or not password or not server:
                return _cors(jsonify({"ok": False, "error": "MT5 login, password and server are required."})), 400
            entry.update({"login": login, "password": password, "server": server})
        creds[broker] = entry
        _save_broker_creds(creds)
        return _cors(jsonify({"ok": True, "account": _public_account(broker, creds)}))

    return _cors(jsonify({"ok": False, "error": "Unhandled broker."})), 400

@app.route("/api/broker/status", methods=["GET", "OPTIONS"])
def api_broker_status():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    creds = _load_broker_creds()
    accounts = []
    for key in creds:
        # refresh live cTrader balances best-effort
        c = creds[key]
        if c.get("type") == "ctrader" and c.get("access_token") and c.get("account_id"):
            ok, result = _ctrader_validate(c["access_token"], c["account_id"], c.get("demo", True))
            if ok and result.get("total_usd") is not None:
                c["last_balance"] = result["total_usd"]
                _save_broker_creds(creds)
        accounts.append(_public_account(key, creds))
    # keep a stable order: paper, ctrader, mt5, ftmo, fundingpips
    order = {"paper": 0, "ctrader": 1, "mt5": 2, "ftmo": 3, "fundingpips": 4}
    accounts.sort(key=lambda a: order.get(a["key"], 9))
    return _cors(jsonify({"ok": True, "accounts": accounts}))

@app.route("/api/broker/positions", methods=["GET", "OPTIONS"])
def api_broker_positions():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    broker = str(request.args.get("broker", "")).lower().strip()
    creds = _load_broker_creds()
    if broker not in creds:
        return _cors(jsonify({"ok": False, "error": "Broker not connected."})), 404
    btype = creds[broker].get("type", broker)
    if btype == "paper":
        return _cors(jsonify({"ok": True, "broker": broker, "positions": []}))
    if btype == "ctrader":
        # Live position fetch via Open API would need a full reconcile flow;
        # report capability honestly until the streaming client lands.
        return _cors(jsonify({"ok": True, "broker": broker, "positions": [],
                              "note": "cTrader position streaming not yet enabled — balance sync is live."}))
    return _cors(jsonify({"ok": True, "broker": broker, "positions": [],
                          "note": "Position sync for this account type needs the terminal bridge."}))

@app.route("/api/broker/disconnect", methods=["POST", "DELETE", "OPTIONS"])
def api_broker_disconnect():
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    broker = str(data.get("broker") or request.args.get("broker", "")).lower().strip()
    creds = _load_broker_creds()
    if broker not in creds:
        return _cors(jsonify({"ok": False, "error": "Broker not connected."})), 404
    del creds[broker]
    _save_broker_creds(creds)
    return _cors(jsonify({"ok": True, "broker": broker, "disconnected": True}))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
