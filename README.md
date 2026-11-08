# Proxy Rotator

A desktop app that routes your internet traffic through a pool of free proxies.
One button gives you a **new IP address** — and it never reuses an IP you have
already used.

- **Desktop app** — a native window (Edge WebView2), not a browser tab. No console window.
- **VPN mode** — one switch sends Windows system traffic (browser and most apps) through the app.
- **NEW IP** — instantly switches to a different, never-before-used IP address.
- **Never reuses an IP** — remembers used addresses in `used.txt`, even across restarts.
- **Verified proxies only** — a proxy is used only after it completes a real HTTPS request.
- **Fast-first** — proxies are ranked by measured latency; dead ones drop out automatically.

> Free proxies are inherently unreliable and slow compared to a paid VPN. This tool
> makes the best of them: it downloads thousands, tests them, keeps the working ones,
> and rotates only through those.

---

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [Command line usage](#command-line-usage)
- [Refreshing the proxy pool](#refreshing-the-proxy-pool)
- [How it works](#how-it-works)
- [Files](#files)
- [Troubleshooting](#troubleshooting)
- [Notes and limitations](#notes-and-limitations)
- [License](#license)

---

## Requirements

| item | version | notes |
|---|---|---|
| Windows | 10 or 11 | VPN mode uses the Windows system proxy |
| Python | **3.11+** | uses `asyncio.timeout` and `StreamWriter.start_tls` |
| pywebview | ≥ 5.0 | the native window (installs Edge WebView2 engine hooks) |
| Edge WebView2 runtime | — | preinstalled on Windows 10/11; otherwise [download it](https://developer.microsoft.com/microsoft-edge/webview2/) |

Everything else is the Python standard library.

## Install

```bat
:: 1. get the code
git clone https://github.com/josmo224/proxy-rotator.git
cd proxy-rotator

:: 2. install the one dependency
python -m pip install -r requirements.txt
```

Or download the ZIP from GitHub, extract it, then:

```bat
cd proxy-rotator
python -m pip install -r requirements.txt
```

## Quick start

```bat
:: build a pool of working proxies (downloads, tests, saves the working ones)
python fetch_proxies.py

:: start the app
python app.py
```

Or double-click **`ProxyRotator.bat`** (or the desktop shortcut if you made one).

Then, in the window:

1. Press **Enable VPN mode** — your browser now routes through the app.
2. Press **NEW IP** whenever you want a different address.
3. Reload your browser tab to browse on the new IP.

Close the window and your normal network settings are restored.

## Using the app

| area | what it does |
|---|---|
| **Rotate** tab | your current exit IP, **NEW IP**, **verify exit IP**, VPN toggle, live request chart |
| **Proxy pool** tab | every proxy with status, latency and last error; filter, add proxies, re-check, fetch fresh |
| **How to use** tab | copy-paste snippets for curl, Python and environment variables |

The big number on the Rotate tab is the **exit IP** — the address websites actually
see. It is verified over HTTPS, so it matches what Google shows when you search
"what is my ip".

If the current IP dies, the app shows *"This IP stopped responding — press NEW IP"*.

## Command line usage

The engine also runs headless, without the window:

```bat
:: hold one IP, change it with Enter (or the /switch endpoint)
python rotator.py --proxies proxies.txt --mode manual

:: a new proxy for every request (for scrapers)
python rotator.py --proxies proxies.txt --mode round-robin
```

The proxy listens on `127.0.0.1:8899`; the dashboard is at
`http://127.0.0.1:8898/`.

Point any tool at it:

```bash
curl -x http://127.0.0.1:8899 https://api.ipify.org
```

```python
import requests
p = {"http": "http://127.0.0.1:8899", "https": "http://127.0.0.1:8899"}
print(requests.get("https://api.ipify.org", proxies=p, timeout=15).text)
```

```bat
set HTTP_PROXY=http://127.0.0.1:8899
set HTTPS_PROXY=http://127.0.0.1:8899
```

Common flags:

| flag | default | meaning |
|---|---|---|
| `--mode` | `round-robin` | `manual`, `round-robin` or `random` |
| `--no-reuse` | off | never use a proxy twice (manual mode always does this) |
| `--allow-reuse` | off | when the pool is exhausted, start over |
| `--port` | `8899` | proxy port |
| `--status-port` | `8898` | dashboard port (`0` disables) |
| `--check-interval` | `300` | seconds between health checks (`0` = once) |
| `--check-concurrency` | `100` | parallel health checks |
| `--no-check` | off | skip health checks entirely |
| `--verbose` | off | log every request |

## Refreshing the proxy pool

Free proxies die constantly. Use **Add fresh proxies** in the app, or:

```bat
python fetch_proxies.py                          :: download + test + save
python fetch_proxies.py --concurrency 400 --timeout 6    :: safest settings
python fetch_proxies.py --recheck-dead           :: second chance for failed proxies
python fetch_proxies.py --recheck-hours 24       :: re-check known proxies idle > 24h
python fetch_proxies.py --limit 5000             :: stop after 5000 working
python fetch_proxies.py --append                 :: merge with the existing file
python fetch_proxies.py --no-check               :: download only
```

> Use moderate `--concurrency` (300–500). Pushing it to 1000+ on a home connection
> exhausts the router's connection table, which produces timeouts and marks working
> proxies as dead.

It pulls from ~45 public list sources, de-duplicates, and keeps only proxies that
complete a real HTTPS request. Results are written to `proxies.txt`, fastest first.

Realistic yield: of ~34,000 raw entries, roughly 5% work, giving around
**1,500–2,000 proxies / ~900 unique IPs** per run.

### Growing the pool every day

Every proxy ever discovered is stored in `proxies.db` (SQLite) with the time it
was first and last seen and its last check result. That means the pool
**accumulates** instead of resetting: proxies that were down yesterday get
re-checked and can come back.

Install a daily automatic refresh (Windows Task Scheduler):

```powershell
powershell -ExecutionPolicy Bypass -File install_daily_task.ps1
```

- runs every day at 03:00 (change with `-At "04:30"`)
- downloads new lists, adds new proxies, and re-checks ones not seen in 24h
- rewrites `proxies.txt` with everything currently working

Remove it later with `... -Remove`. Run it once by hand any time with
`daily_refresh.bat`.

> **On "millions of IPs":** public free lists hold ~30–40k entries at any moment,
> of which ~5% work — so a single run yields roughly 900 unique working IPs, and
> the database grows by a few thousand entries per day as new proxies appear.
> Millions of usable IPs only exist with paid providers (Bright Data, Oxylabs,
> etc.), which are billed per GB. This tool works with any proxy list you supply,
> including a paid one.

## How it works

```
app / browser ──► 127.0.0.1:8899 (this app) ──► upstream free proxy ──► website
```

- The app is a local HTTP/CONNECT proxy. HTTPS is tunnelled, never decrypted.
- In **manual** mode one proxy is held for all traffic; **NEW IP** moves to the
  next unused address (tracked per IP, not per port).
- Every candidate is health-checked with a real HTTPS request, then ranked by latency.
- The dashboard, `used.txt` and `current.txt` survive restarts.

## Files

| file | purpose |
|---|---|
| `app.py` | desktop app: native window + engine |
| `rotator.py` | proxy engine and local dashboard/API |
| `webui.py` | the interface (HTML/CSS/JS) |
| `sysproxy.py` | Windows system-proxy (VPN mode) toggle |
| `fetch_proxies.py` | download and validate proxy lists |
| `proxy_store.py` | SQLite store of every proxy ever seen |
| `daily_refresh.bat` | one-shot daily refresh |
| `install_daily_task.ps1` | registers the daily scheduled task |
| `make_icon.py` | regenerates `proxyrotator.ico` (needs Pillow) |
| `test_rotator.py` | self-test suite |
| `proxies.example.txt` | proxy file format |
| `proxies.txt` | your pool (generated, not committed) |
| `used.txt` / `current.txt` | rotation memory (generated) |

## Troubleshooting

**"The desktop window needs pywebview"**
```bat
python -m pip install -r requirements.txt
```

**Window opens blank**
Install/repair the Edge WebView2 runtime:
<https://developer.microsoft.com/microsoft-edge/webview2/>

**"Proxy Rotator is already running"**
Close the existing window, or end the process in Task Manager, then retry.

**No internet after closing the app**
VPN mode should restore your settings on exit. If it did not, run:
```bat
python -c "import sysproxy; sysproxy.disable()"
```
or turn the proxy off in Settings → Network → Proxy.

**Browser shows a different IP than the app**
The app shows the *exit* IP (verified over HTTPS). Plain-HTTP sites can be
forwarded by transparent proxies using your real IP — this is why the check uses
HTTPS. Reload the browser tab after pressing NEW IP.

**Everything is slow**
Free proxies are the bottleneck. Press **Add fresh proxies** to rebuild the pool,
and keep the fastest proxies by running the fetcher with a low `--timeout`.

## Notes and limitations

- Free proxies are untrusted by nature: an upstream can read or modify plain-HTTP
  traffic. HTTPS is tunnelled end-to-end and never decrypted by this app.
- Only proxies that pass a real request are used, but free proxies can still die
  mid-session — press **NEW IP** if a site fails.
- Respect the terms of service of the sites you use this against.

## License

MIT — see [LICENSE](LICENSE).
