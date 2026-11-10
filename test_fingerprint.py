"""Probe two launched browsers and confirm their fingerprints differ."""
import json
import subprocess
import sys
import time

sys.path.insert(0, ".")
import browser_launcher as bl
import fingerprint

PROBE = r"""
JSON.stringify({
  ua: navigator.userAgent,
  platform: navigator.platform,
  hc: navigator.hardwareConcurrency,
  dm: navigator.deviceMemory,
  screen: screen.width + 'x' + screen.height,
  webgl: (() => {
    const c = document.createElement('canvas');
    const g = c.getContext('webgl');
    return g ? g.getParameter(37446) : null;
  })(),
  canvas: (() => {
    const c = document.createElement('canvas');
    c.width = 220; c.height = 60;
    const x = c.getContext('2d');
    x.textBaseline = 'top'; x.font = '16px Arial';
    x.fillStyle = '#f60'; x.fillRect(10, 10, 100, 30);
    x.fillStyle = '#069'; x.fillText('fingerprint test', 12, 12);
    const s = c.toDataURL(); let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h.toString(16);
  })()
})
"""


def probe(port):
    ws = fingerprint._WS(fingerprint._debug_ws_url(port))
    try:
        r = ws.call(1, "Runtime.evaluate",
                    {"expression": PROBE, "returnByValue": True})
        return json.loads(r["result"]["result"]["value"])
    finally:
        ws.close()


def run_once():
    info = bl.launch("127.0.0.1:8899", "data:text/html,<title>fp</title>", headless=True)
    time.sleep(1.5)
    data = probe(info["devtools_port"])
    return info, data


a_info, a = run_once()
b_info, b = run_once()

for label, d in (("A", a), ("B", b)):
    print(f"--- browser {label} ---")
    print("  ua      :", d["ua"])
    print("  platform:", d["platform"], "| hc:", d["hc"], "| mem:", d["dm"])
    print("  screen  :", d["screen"])
    print("  webgl   :", d["webgl"])
    print("  canvas  :", d["canvas"])

diff = [k for k in ("platform", "hc", "dm", "screen", "webgl", "canvas") if a[k] != b[k]]
print("\ndiffering fields:", diff)

# clean up the headless browsers
for info in (a_info, b_info):
    subprocess.run(
    ["wmic", "process", "where",
     "(CommandLine like '%ProxyRotator%profiles%' and name='chrome.exe')",
     "call", "terminate"], capture_output=True)

ok = len(diff) >= 3
print("PASS" if ok else "FAIL: too few fields differ")
sys.exit(0 if ok else 1)
