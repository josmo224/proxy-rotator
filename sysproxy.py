"""
sysproxy.py - turn the Windows system proxy on and off from the app.

Sets HKCU\\...\\Internet Settings\\ProxyEnable / ProxyServer, then tells
WinINet to reload so Chrome, Edge and the rest pick it up immediately.
Only touches the current user's settings; a toggle restores the previous
state when you turn it off.
"""
from __future__ import annotations

import ctypes
import json
import sys

KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PREV_FILE = None  # set by caller to remember the original setting


def _read_reg():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        def get(name, default):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except FileNotFoundError:
                return default
        return int(get("ProxyEnable", 0)), get("ProxyServer", ""), get("ProxyOverride", "")


def _write_reg(enable: int, server: str | None, override: str | None = None):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, enable)
        if server is not None:
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server)
        if override is not None:
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, override)


def _refresh():
    """Tell WinINet the settings changed, so browsers re-read them without a restart."""
    internet_set_option = ctypes.windll.wininet.InternetSetOptionW
    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
    internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)


def _winhttp_set(server: str | None) -> None:
    """Also set the WinHTTP proxy (covers services/apps that ignore WinINet)."""
    import subprocess
    try:
        if server:
            subprocess.run(
                ["netsh", "winhttp", "set", "proxy", server, "bypass-list=<local>"],
                capture_output=True, timeout=8, creationflags=0x08000000,
            )
        else:
            subprocess.run(
                ["netsh", "winhttp", "reset", "proxy"],
                capture_output=True, timeout=8, creationflags=0x08000000,
            )
    except Exception:
        pass  # needs admin for some systems; WinINet alone still covers browsers


def status() -> dict:
    if sys.platform != "win32":
        return {"supported": False, "on": False, "server": ""}
    enable, server, _ = _read_reg()
    return {"supported": True, "on": bool(enable), "server": server}


def enable(address: str) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("system proxy is Windows-only")
    prev_enable, prev_server, prev_override = _read_reg()
    # remember original state so 'off' can restore it
    global PREV_FILE
    if PREV_FILE is not None:
        try:
            PREV_FILE.write_text(
                json.dumps({"enable": prev_enable, "server": prev_server,
                            "override": prev_override}),
                encoding="utf-8",
            )
        except OSError:
            pass
    # bypass localhost so the dashboard and local dev servers never get proxied
    override = "<local>;localhost;127.0.0.1;::1"
    _write_reg(1, address, override)
    _winhttp_set(address)
    _refresh()
    return status()


def disable() -> dict:
    if sys.platform != "win32":
        raise RuntimeError("system proxy is Windows-only")
    enable_v, server, override = 0, "", ""
    global PREV_FILE
    if PREV_FILE is not None and PREV_FILE.exists():
        try:
            prev = json.loads(PREV_FILE.read_text(encoding="utf-8"))
            enable_v = int(prev.get("enable", 0))
            server = prev.get("server") or ""
            override = prev.get("override", "")
            PREV_FILE.unlink()
        except (OSError, ValueError):
            pass
    _write_reg(enable_v, server, override)
    if enable_v and server:
        _winhttp_set(server)
    else:
        _winhttp_set(None)
    _refresh()
    return status()
