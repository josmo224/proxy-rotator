"""The desktop app's interface. Served by rotator.py and shown in a native window."""

DASHBOARD = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Proxy Rotator</title>
<style>
:root{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --surface-2:#212120;
  --ink:#f0efec; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --accent:#3987e5; --accent-hi:#5598e7;
  --radius:12px;
  --font: system-ui,-apple-system,"Segoe UI",sans-serif;
}
:root[data-theme="light"]{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f2f2ef;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0; background:var(--page); color:var(--ink);
  font:14px/1.5 var(--font); -webkit-font-smoothing:antialiased;
  overflow:hidden;
}
.app{display:grid; grid-template-columns:264px 1fr; height:100vh}

/* ---------- sidebar ---------- */
aside{
  background:var(--surface); border-right:1px solid var(--ring);
  padding:20px 16px; display:flex; flex-direction:column; gap:18px; overflow:auto;
}
.brand{display:flex;align-items:center;gap:10px;padding:0 4px}
.logo{width:30px;height:30px;border-radius:8px;flex:none;
  background:linear-gradient(135deg,var(--s1),var(--s3));
  display:grid;place-items:center;color:#fff;font-weight:700;font-size:15px}
.brand b{font-size:15px;letter-spacing:-.01em}
.brand small{display:block;color:var(--muted);font-size:11px;font-weight:400}
.nav{display:flex;flex-direction:column;gap:2px}
.nav button{
  all:unset; box-sizing:border-box; width:100%; cursor:pointer; padding:9px 12px;
  border-radius:8px; color:var(--ink-2); display:flex;align-items:center;gap:10px; font-size:13px;
}
.nav button:hover{background:var(--surface-2);color:var(--ink)}
.nav button.on{background:var(--surface-2);color:var(--ink);font-weight:600}
.nav svg{width:16px;height:16px;flex:none}
.side-foot{margin-top:auto;padding:12px 4px 0;border-top:1px solid var(--ring)}
.side-foot .k{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em}
.side-foot .v{font-size:12px;color:var(--ink-2);margin-top:2px;word-break:break-all;font-variant-numeric:tabular-nums}

/* ---------- main ---------- */
main{padding:24px 26px; overflow:auto; display:flex;flex-direction:column;gap:18px}
.page-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.page-head h1{font-size:18px;margin:0;letter-spacing:-.01em}
.page-head p{margin:2px 0 0;color:var(--muted);font-size:12px}
.pill{font-size:11px;color:var(--ink-2);border:1px solid var(--ring);border-radius:999px;
  padding:3px 10px;display:inline-flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot.g{background:var(--good)}.dot.w{background:var(--warn)}.dot.c{background:var(--critical)}.dot.u{background:var(--muted)}

/* hero */
.hero{background:var(--surface);border:1px solid var(--ring);border-radius:var(--radius);
  padding:20px 22px;display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.hero .label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em}
.hero .ip{font-size:26px;font-weight:650;letter-spacing:-.02em;margin:4px 0;
  font-variant-numeric:tabular-nums;word-break:break-all}
.hero .sub{display:flex;gap:16px;color:var(--ink-2);font-size:12px;flex-wrap:wrap}
.hero .sub b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.hero-actions{display:flex;flex-direction:column;gap:8px;align-items:stretch}
#newip{all:unset;box-sizing:border-box;cursor:pointer;text-align:center;
  background:var(--accent);color:#fff;font-weight:650;font-size:15px;
  padding:13px 26px;border-radius:10px;transition:background .15s;white-space:nowrap;display:flex;
  align-items:center;justify-content:center;gap:8px}
#newip:hover{background:var(--accent-hi)}
#newip:active{transform:translateY(1px)}
#newip:disabled{opacity:.55;cursor:wait}
#newip svg{width:16px;height:16px}
.btn-2{all:unset;box-sizing:border-box;cursor:pointer;text-align:center;font-size:12px;
  color:var(--ink-2);border:1px solid var(--ring);border-radius:8px;padding:8px 14px}
.btn-2:hover{background:var(--surface-2);color:var(--ink)}

/* stat tiles */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:var(--radius);padding:14px 16px}
.tile .k{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.09em}
.tile .v{font-size:26px;font-weight:650;margin-top:4px;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:6px}
.tile .v small{font-size:13px;color:var(--muted);font-weight:400}
.tile .spark{display:flex;align-items:flex-end;gap:2px;height:22px;margin-top:10px}
.tile .spark i{flex:1;border-radius:1.5px;min-height:22px;opacity:.9}

/* chart card */
.card{background:var(--surface);border:1px solid var(--ring);border-radius:var(--radius);padding:16px 18px}
.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:12px}
.card-head h2{font-size:13px;margin:0;font-weight:600}
.card-head .hint{color:var(--muted);font-size:11px}
.legend{display:flex;gap:14px;font-size:11px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.swatch{width:10px;height:10px;border-radius:3px}
#chart{width:100%;height:120px;display:block}
.tooltip{position:fixed;pointer-events:none;background:var(--surface-2);border:1px solid var(--ring);
  border-radius:8px;padding:7px 10px;font-size:11.5px;color:var(--ink);box-shadow:0 8px 24px rgba(0,0,0,.35);
  opacity:0;transition:opacity .1s;z-index:50;white-space:nowrap}
.tooltip b{font-variant-numeric:tabular-nums}

/* proxy table */
.table-card{display:flex;flex-direction:column;min-height:0}
.tools{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.search{flex:1;min-width:160px;position:relative}
.search input{width:100%;all:unset;box-sizing:border-box;background:var(--surface-2);
  border:1px solid var(--ring);border-radius:8px;padding:8px 12px 8px 32px;font-size:12.5px;color:var(--ink)}
.search svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:var(--muted)}
.seg{display:flex;background:var(--surface-2);border:1px solid var(--ring);border-radius:8px;padding:2px}
.seg button{all:unset;cursor:pointer;font-size:12px;padding:5px 12px;border-radius:6px;color:var(--ink-2)}
.seg button.on{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.3)}
.tblwrap{overflow:auto;border:1px solid var(--ring);border-radius:10px;flex:1;min-height:120px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
thead th{position:sticky;top:0;background:var(--surface-2);color:var(--muted);font-weight:500;
  text-align:left;padding:9px 12px;text-transform:uppercase;font-size:10px;letter-spacing:.07em;z-index:1}
tbody td{padding:8px 12px;border-top:1px solid var(--ring);font-variant-numeric:tabular-nums}
tbody tr:hover{background:var(--surface-2)}
td.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px}
td.err{color:var(--muted);font-size:11px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.status{display:inline-flex;align-items:center;gap:7px;font-size:12px}
.curtag{color:var(--s1);font-size:10.5px;font-weight:600;margin-left:6px}
.downwarn{margin-top:8px;font-size:12px;color:var(--critical);background:rgba(208,59,59,.12);
border:1px solid rgba(208,59,59,.4);border-radius:8px;padding:6px 10px;display:inline-block}
.downwarn b{color:var(--critical)}
.empty{padding:28px;text-align:center;color:var(--muted);font-size:12.5px}

/* add panel */
.add-row{display:flex;gap:8px;align-items:flex-start}
textarea{flex:1;all:unset;box-sizing:border-box;background:var(--surface-2);border:1px solid var(--ring);
  border-radius:9px;padding:10px 12px;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--ink);min-height:64px;resize:vertical}
textarea::placeholder{color:var(--muted)}
.btn-primary{all:unset;box-sizing:border-box;cursor:pointer;background:var(--surface-2);
  border:1px solid var(--ring);border-radius:9px;padding:10px 16px;font-size:12.5px;font-weight:600;
  color:var(--ink);white-space:nowrap}
.btn-primary:hover{border-color:var(--accent)}
.msg{font-size:12px;color:var(--muted);align-self:center}
.hidden{display:none !important}
.section{display:none;flex-direction:column;gap:18px;min-height:0}
.section.on{display:flex}
@media(max-width:900px){
  .app{grid-template-columns:1fr}
  aside{display:none}
  .tiles{grid-template-columns:repeat(2,1fr)}
}
</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">
      <div class="logo">P</div>
      <div><b>Proxy Rotator</b><small>local rotating proxy</small></div>
    </div>
    <nav class="nav">
      <button class="on" data-tab="run">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>
        Rotate
      </button>
      <button data-tab="pool">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>
        Proxy pool
      </button>
      <button data-tab="help">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7v.5M12 17h.01"/></svg>
        How to use
      </button>
    </nav>
    <div class="side-foot">
      <div class="k">proxy address</div>
      <div class="v" id="addr">127.0.0.1:8899</div>
    </div>
  </aside>

  <main>
    <!-- ROTATE -->
    <section class="section on" id="tab-run">
      <div class="page-head">
        <div>
          <h1>Rotate</h1>
          <p>Every request through the proxy uses the IP you pick here.</p>
        </div>
        <span class="pill" id="checkpill"><span class="dot u"></span> checking…</span>
      </div>

      <div class="hero">
        <div style="min-width:0;flex:1">
          <div class="label">Your IP (exit)</div>
          <div class="ip" id="cur">—</div>
          <div class="sub" id="proxysub"><span id="proxyaddr">connecting…</span></div>
          <div class="downwarn hidden" id="downwarn">
            This IP stopped responding — press <b>NEW IP</b> to switch.
          </div>
          <div class="sub">
            <span><b id="remN">—</b> unused</span>
            <span><b id="usedN">—</b> used</span>
            <span><b id="aliveN">—</b> alive</span>
          </div>
        </div>
        <div class="hero-actions">
          <button id="newip" onclick="switchIp()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15"/></svg>
            NEW IP
          </button>
          <button class="btn-2" onclick="checkIp()">verify exit IP</button>
          <button class="btn-2" id="systoggle" onclick="toggleSysProxy()" title="Route all apps through this app">Enable VPN mode</button>
        </div>
      </div>

      <div class="tiles">
        <div class="tile"><div class="k">Uptime</div><div class="v" id="t-uptime">—</div></div>
        <div class="tile"><div class="k">Requests</div><div class="v" id="t-req">—</div></div>
        <div class="tile"><div class="k">Failed</div><div class="v" id="t-fail">—</div></div>
        <div class="tile">
          <div class="k">Proxy pool</div>
          <div class="v" id="t-pool">—<small></small></div>
          <div class="spark" id="spark"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <h2>Requests per second</h2>
          <div class="legend">
            <span><i class="swatch" style="background:var(--s1)"></i>ok</span>
            <span><i class="swatch" style="background:var(--s2)"></i>failed</span>
          </div>
        </div>
        <svg id="chart" preserveAspectRatio="none"></svg>
      </div>
    </section>

    <!-- POOL -->
    <section class="section" id="tab-pool">
      <div class="page-head">
        <div>
          <h1>Proxy pool</h1>
          <p>Proxies are health-checked continuously; dead ones drop out automatically.</p>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn-primary" id="fetchbtn" onclick="fetchFresh()">Add fresh proxies</button>
          <button class="btn-primary" onclick="reload()">Re-check all</button>
        </div>
      </div>

      <div class="table-card card">
        <div class="tools">
          <div class="search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
            <input id="filter" placeholder="filter by host or scheme…" oninput="renderTable()">
          </div>
          <div class="seg" id="seg">
            <button class="on" data-f="all">All</button>
            <button data-f="alive">Alive</button>
            <button data-f="dead">Dead</button>
          </div>
        </div>
        <div class="tblwrap">
          <table>
            <thead><tr>
              <th>Status</th><th>Proxy</th><th>Latency</th><th>OK</th><th>Fail</th><th>Last error</th>
            </tr></thead>
            <tbody id="rows"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>Add proxies</h2><span class="hint">one per line · host:port or scheme://user:pass@host:port</span></div>
        <div class="add-row">
          <textarea id="add" placeholder="1.2.3.4:8080&#10;socks5://user:pass@5.6.7.8:1080"></textarea>
          <button class="btn-primary" onclick="addProxies()">Add &amp; check</button>
        </div>
        <div class="msg" id="msg" style="margin-top:8px"></div>
      </div>
    </section>

    <!-- HELP -->
    <section class="section" id="tab-help">
      <div class="page-head"><div><h1>How to use</h1><p>Point any app at the local proxy address.</p></div></div>
      <div class="card">
        <div class="card-head"><h2>Proxy settings</h2></div>
        <p style="color:var(--ink-2);margin:0 0 12px;font-size:13px">
          Use <b style="color:var(--ink)">HTTP proxy</b> <code id="addr2">127.0.0.1:8899</code> in the app.
          For Chrome/Firefox, install FoxyProxy or SwitchyOmega and add it as an HTTP proxy.
        </p>
        <div class="card-head" style="margin-top:16px"><h2>curl</h2></div>
        <pre>curl -x http://127.0.0.1:8899 https://httpbin.org/ip</pre>
        <div class="card-head" style="margin-top:16px"><h2>Python (requests)</h2></div>
        <pre>import requests
p = {"http": "http://127.0.0.1:8899", "https": "http://127.0.0.1:8899"}
r = requests.get("https://httpbin.org/ip", proxies=p, timeout=15)
print(r.json())</pre>
        <div class="card-head" style="margin-top:16px"><h2>Environment variables</h2></div>
        <pre>set HTTP_PROXY=http://127.0.0.1:8899
set HTTPS_PROXY=http://127.0.0.1:8899</pre>
        <p style="color:var(--muted);font-size:12px;margin-top:16px">
          Note: a browser keeps already-open connections on the old IP after you press
          <b>NEW IP</b>. Reload the page or open a new tab to browse on the new IP.
        </p>
      </div>
    </section>
  </main>
</div>
<div class="tooltip" id="tip"></div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = s => {
  s = Math.floor(s || 0);
  const h = Math.floor(s/3600), m = Math.floor(s%3600/60), sec = s%60;
  return (h ? h+'h ' : '') + m + 'm ' + sec + 's';
};
const fmtN = n => n >= 1000 ? (n/1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n ?? 0);

let data = {}, filt = 'all', hist = [];
const MAXH = 60;

/* tabs */
document.querySelectorAll('.nav button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('.nav button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.section').forEach(s =>
      s.classList.toggle('on', s.id === 'tab-' + b.dataset.tab));
    if (b.dataset.tab === 'pool') renderTable();
  };
});
/* alive/dead segment */
document.querySelectorAll('#seg button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('#seg button').forEach(x => x.classList.toggle('on', x === b));
    filt = b.dataset.f; renderTable();
  };
});

function aliveClass(a) { return a === true ? 'g' : a === false ? 'c' : 'u'; }
function aliveLabel(a) { return a === true ? 'alive' : a === false ? 'dead' : 'unchecked'; }

async function load() {
  try {
    const r = await fetch('/stats', {cache: 'no-store'});
    data = await r.json();
  } catch (e) { $('checkpill').innerHTML = '<span class="dot c"></span> server offline'; return; }
  const p = data.pool || {};

  // the proxy can change without a button press (auto-failover) - re-verify
  if (p.current !== lastCur) {
    const changed = lastCur !== null;
    lastCur = p.current;
    if (changed) { exitIp = null; setTimeout(verifyIp, 0); }
  }

  // big number = the address the world sees (verified exit IP); fall back to the
  // proxy address until the first verification completes
  $('cur').textContent = exitIp || p.current || (data.mode === 'manual' ? 'no proxy selected' : 'rotates every request');
  $('proxyaddr').textContent = p.current ? ('via ' + p.current) : '';
  $('remN').textContent = fmtN(p.remaining ?? 0);
  $('usedN').textContent = fmtN(p.used ?? 0);
  $('aliveN').textContent = fmtN(p.alive ?? 0);

  const warn = $('downwarn');
  if (p.current_ok === false) {
    warn.classList.remove('hidden');
  } else {
    warn.classList.add('hidden');
  }

  $('t-uptime').textContent = fmt(data.uptime);
  $('t-req').textContent = fmtN(data.requests);
  $('t-fail').textContent = fmtN(data.failures);
  $('t-pool').innerHTML = fmtN(p.total ?? 0) + '<small>proxies</small>';

  const alive = p.alive || 0, dead = p.dead || 0;
  const cls = data.pool && data.pool.total && alive === 0 ? 'c' : (dead > alive ? 'w' : 'g');
  $('checkpill').innerHTML = `<span class="dot ${cls}"></span> ${alive} alive · ${dead} dead`;

  $('addr').textContent = data.addr || '127.0.0.1:8899';
  $('addr2').textContent = data.addr || '127.0.0.1:8899';
  updateSysProxy(data.system_proxy);

  hist.push([data.requests, data.failures]);
  if (hist.length > MAXH) hist.shift();
  drawChart();
  drawSpark();
  renderTable();
}

/* per-second deltas for the line chart */
let lastReq = null, lastFail = null;
function deltas() {
  const out = [];
  if (lastReq === null) return out;
  return [[Math.max(0, data.requests - lastReq), Math.max(0, data.failures - lastFail)]];
}
let rateHist = [];
function pushRate() {
  if (lastReq !== null) rateHist.push([Math.max(0, data.requests - lastReq), Math.max(0, data.failures - lastFail)]);
  else rateHist.push([0, 0]);
  if (rateHist.length > MAXH) rateHist.shift();
  lastReq = data.requests; lastFail = data.failures;
}

function drawChart() {
  const svg = $('chart');
  const W = svg.clientWidth || 600, H = 120, pad = 4;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const n = rateHist.length;
  if (!n) { svg.innerHTML = ''; return; }
  let maxV = 1;
  rateHist.forEach(r => { maxV = Math.max(maxV, r[0] + r[1]); });
  maxV = Math.ceil(maxV * 1.15);
  const bw = W / MAXH;
  const x = i => i * (W / Math.max(MAXH, n)) + (W / Math.max(MAXH, n) - Math.max(bw * 0.72, 1)) / 2;
  const bwid = Math.max(Math.min(bw * 0.72, 14), 1.5);
  let s = '';
  // gridlines
  for (let g = 0; g <= 3; g++) {
    const y = pad + (H - pad * 2) * g / 3;
    s += `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
  }
  rateHist.forEach((r, i) => {
    const total = r[0] + r[1];
    let y = H - pad;
    const okH = (r[0] / maxV) * (H - pad * 2);
    const failH = (r[1] / maxV) * (H - pad * 2);
    const cx = x(i);
    if (r[0] > 0) s += `<rect x="${cx}" y="${y - okH}" width="${bwid}" height="${okH}" rx="1.5" fill="var(--s1)"/>`;
    if (r[1] > 0) s += `<rect x="${cx}" y="${y - okH - failH}" width="${bwid}" height="${failH}" rx="1.5" fill="var(--s2)"/>`;
  });
  svg.innerHTML = s;
  svg._rate = rateHist.slice(); svg._W = W; svg._bwid = bwid; svg._n = n;
}

function drawSpark() {
  const el = $('spark');
  const p = data.pool || {};
  const total = p.total || 1, alive = p.alive || 0, used = p.used || 0;
  const segs = [];
  const usedPct = Math.min(1, used / total), alivePct = Math.min(1 - usedPct, alive / total);
  for (let i = 0; i < 22; i++) segs.push(i / 22 < usedPct ? 'var(--muted)' : (i / 22 < usedPct + alivePct ? 'var(--s3)' : 'var(--grid)'));
  el.innerHTML = segs.map(c => `<i style="background:${c}"></i>`).join('');
}

function renderTable() {
  if (!document.getElementById('tab-pool').classList.contains('on') && !document.getElementById('tab-run').classList.contains('on')) return;
  const q = ($('filter')?.value || '').toLowerCase();
  let rows = data.proxies || [];
  rows = rows.filter(p => {
    if (filt === 'alive' && p.alive !== true) return false;
    if (filt === 'dead' && p.alive !== false) return false;
    if (q && !p.proxy.toLowerCase().includes(q)) return false;
    return true;
  });
  const tb = $('rows');
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="6"><div class="empty">${data.proxies?.length ? 'No proxies match the filter.' : 'No proxies loaded. Use the Add panel below or the fetch script.'}</div></td></tr>`;
    return;
  }
  const live = rows.filter(p => p.alive === true).length;
  tb.innerHTML = rows.slice(0, 500).map(p => {
    const c = aliveClass(p.alive);
    return `<tr>
      <td><span class="status"><span class="dot ${c}"></span>${aliveLabel(p.alive)}</span></td>
      <td class="mono">${esc(p.proxy)}${p.current ? ' <span class="curtag">◂ current</span>' : ''}</td>
      <td>${p.latency != null ? p.latency + ' ms' : '—'}</td>
      <td>${p.successes}</td>
      <td>${p.failures}</td>
      <td class="err" title="${esc(p.error || '')}">${esc(p.error || '—')}</td>
    </tr>`;
  }).join('') + (rows.length > 500 ? `<tr><td colspan="6"><div class="empty">+ ${rows.length - 500} more — refine the filter</div></td></tr>` : '');
}

let exitIp = null;
let lastCur = null;

async function switchIp() {
  const b = $('newip'); b.disabled = true;
  const old = b.innerHTML; b.innerHTML = 'switching…';
  exitIp = null;
  try {
    const r = await fetch('/switch', {method: 'POST'});
    const j = await r.json();
    if (j.cycle_reset) {
      $('proxyaddr').textContent = 'pool cycle restarted (every IP had been used)';
    } else if (!j.ok) {
      $('proxyaddr').textContent = 'no working proxy available right now';
    }
  } catch (e) {}
  lastReq = null; await load();
  b.disabled = false; b.innerHTML = old;
  verifyIp();                 // confirm the new IP automatically
}

async function verifyIp() {
  $('cur').textContent = exitIp || 'verifying…';
  try {
    const r = await fetch('/ip', {cache: 'no-store'}); const j = await r.json();
    exitIp = j.ip || null;
    if (!j.ip) $('proxyaddr').textContent = 'exit IP check failed — proxy may be down, press NEW IP';
  } catch (x) { exitIp = null; }
  await load();
}

async function checkIp() { verifyIp(); }

/* system (browser) proxy toggle */
let sysState = null;
function updateSysProxy(sp) {
  sysState = sp;
  const b = $('systoggle');
  if (!sp || sp.supported === false) {
    b.classList.add('hidden');
    return;
  }
  b.classList.remove('hidden');
  b.textContent = sp.on ? 'VPN mode: ON' : 'Enable VPN mode';
  b.style.borderColor = sp.on ? 'var(--good)' : '';
  b.style.color = sp.on ? 'var(--good)' : '';
}
async function toggleSysProxy() {
  if (!sysState || !sysState.supported) return;
  const want = sysState.on ? 'off' : 'on';
  $('systoggle').textContent = 'waiting…';
  try {
    const r = await fetch('/sysproxy', {method: 'POST', body: want});
    const j = await r.json();
    if (!j.ok) { $('proxyaddr').textContent = 'Browser proxy: ' + (j.error || 'failed'); }
    else if (j.on) { $('proxyaddr').textContent = 'Browser proxy ON — reload your browser tab to use this IP.'; }
  } catch (e) { $('proxyaddr').textContent = 'Browser proxy toggle failed'; }
  setTimeout(load, 400);
}

async function reload() {
  $('msg').textContent = 're-checking all proxies…';
  await fetch('/reload', {method: 'POST'});
  $('msg').textContent = 're-check started — results update live.';
  setTimeout(load, 1200);
}

/* download + validate a fresh batch of free proxies */
let fetchPoll = null;
async function fetchFresh() {
  const b = $('fetchbtn');
  b.disabled = true; b.textContent = 'downloading…';
  $('msg').textContent = 'Downloading proxy lists from public sources… this takes a few minutes.';
  await fetch('/fetch', {method: 'POST'});
  clearInterval(fetchPoll);
  fetchPoll = setInterval(async () => {
    try {
      const r = await fetch('/fetch-status'); const j = await r.json();
      if (j.running) { $('msg').textContent = 'Testing proxies… (running in background)'; return; }
      clearInterval(fetchPoll);
      b.disabled = false; b.textContent = 'Add fresh proxies';
      if (j.result && j.result.ok) {
        $('msg').textContent = `Refreshed: tested ${j.result.downloaded}, ${j.result.working} working.`;
        load();
      } else {
        $('msg').textContent = 'Refresh failed: ' + (j.result?.error || 'unknown');
      }
    } catch (e) {}
  }, 2000);
}

async function addProxies() {
  const t = $('add').value.trim();
  if (!t) return;
  $('msg').textContent = 'adding…';
  const r = await fetch('/add', {method: 'POST', headers: {'content-type': 'text/plain'}, body: t});
  const j = await r.json();
  $('msg').textContent = `added ${j.added} (${j.skipped} duplicate)` + (j.invalid ? `, ${j.invalid} invalid` : '');
  $('add').value = '';
  setTimeout(load, 900);
}

/* init */
pushRate(); load(); verifyIp();
setInterval(() => { pushRate(); load(); }, 2000);
window.addEventListener('resize', drawChart);
</script>
</body>
</html>
"""
