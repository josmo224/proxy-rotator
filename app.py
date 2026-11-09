#!/usr/bin/env python3
"""
app.py - the desktop app. Opens the rotator in a native window (Edge WebView2
on Windows). No browser tab, no console window: just the app.

    pythonw app.py        (or double-click ProxyRotator.bat)

The proxy engine runs inside this process; the window shows the interface,
the NEW IP button, live stats and the proxy pool.
"""
from __future__ import annotations

import asyncio
import atexit
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import rotator  # noqa: E402


def free_port(preferred: int) -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        try:
            s.close()
        except Exception:
            pass


def build_config(proxy_port: int, ui_port: int):
    cfg = rotator.build_parser().parse_args([])   # defaults
    cfg.proxies = str(HERE / "proxies.txt")
    cfg.port = proxy_port
    cfg.status_port = ui_port
    cfg.mode = "manual"
    cfg.host = "127.0.0.1"
    # Gentle background checking so it never competes with browsing, but high
    # enough that a full pass over the (small, high-quality) pool finishes quickly.
    cfg.check_interval = 3600
    cfg.check_concurrency = 250
    cfg.timeout = 8
    # verify against the same host the exit-IP check uses, so a proxy that
    # passes verification is one that actually works end to end
    cfg.check_target = "api.ipify.org:443"
    cfg.proxies_path = Path(cfg.proxies)
    cfg.check_host, cfg.check_port = rotator.split_host_port(cfg.check_target, 443)
    return cfg


def start_engine(proxy_port: int, ui_port: int) -> threading.Thread:
    cfg = build_config(proxy_port, ui_port)

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(rotator.run(cfg))
        except Exception as exc:  # noqa: BLE001
            print("engine stopped:", exc)

    t = threading.Thread(target=runner, daemon=True, name="proxy-engine")
    t.start()
    return t


def wait_ready(port: int, timeout: float = 15) -> bool:
    import socket
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.4).close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def port_in_use(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def apply_window_icon() -> None:
    """Give the window and taskbar the app icon."""
    try:
        import ctypes
        from ctypes import wintypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ProxyRotator.App")
        ico_path = str(HERE / "proxyrotator.ico")
        if not Path(ico_path).exists():
            return
        # IMAGE_ICON=1, LR_LOADFROMFILE=0x10
        flags = 0x10
        big = ctypes.windll.user32.LoadImageW(None, ico_path, 1, 0, 0, flags)
        small = ctypes.windll.user32.LoadImageW(None, ico_path, 1, 16, 16, flags)
        hwnd = ctypes.windll.user32.FindWindowW(None, "Proxy Rotator")
        if not hwnd:
            return
        WM_SETICON = 0x0080
        if small:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, small)   # ICON_SMALL
        if big:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, big)     # ICON_BIG
    except Exception:
        pass


def main() -> int:
    try:
        import webview
    except ImportError:
        print("The desktop window needs pywebview:\n    python -m pip install pywebview")
        return 1

    # Single instance: if the app is already running, just say so and exit.
    if port_in_use(8898) or port_in_use(8899):
        print("Proxy Rotator is already running - use the existing window.")
        return 0

    proxy_port, ui_port = 8899, 8898
    start_engine(proxy_port, ui_port)

    if not wait_ready(ui_port):
        print("engine did not start")
        return 1

    # VPN-like: route the whole system through the app as soon as it opens,
    # and always restore the user's normal settings when it closes.
    def restore_proxy():
        try:
            rotator._sysproxy_disable()
        except Exception:
            pass

    atexit.register(restore_proxy)
    try:
        rotator._sysproxy_enable(f"127.0.0.1:{proxy_port}")
    except Exception:
        pass

    window = webview.create_window(
        "Proxy Rotator",
        f"http://127.0.0.1:{ui_port}/",
        width=1180,
        height=820,
        min_size=(880, 620),
        background_color="#0d0d0d",
    )

    try:
        webview.start(apply_window_icon, debug=False)
    finally:
        restore_proxy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
