"""
browser_launcher.py - open an isolated browser instance routed through the app.

Each launch gets:
  - a brand-new profile directory (no cookies, storage, cache or history)
  - a user agent that matches the Chrome/Edge version actually installed
  - a common screen size and language chosen at random
  - WebRTC restricted to the proxy, so the real IP is not leaked

This is profile isolation + coherent metadata, not a full anti-detect browser:
it does not spoof canvas, WebGL or font fingerprints.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

_RESOLUTIONS = [
    (1920, 1080), (1536, 864), (1600, 900), (1366, 768),
    (1440, 900), (1680, 1050), (1280, 720), (2560, 1440),
]
_LANGS = ["en-US", "en-US", "en-US", "en-GB"]
_MAX_PROFILES = 25


def _install_dirs() -> list[tuple[Path, str]]:
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return [
        (pf / "Google" / "Chrome" / "Application", "chrome"),
        (pf86 / "Google" / "Chrome" / "Application", "chrome"),
        (local / "Google" / "Chrome" / "Application", "chrome"),
        (pf / "Microsoft" / "Edge" / "Application", "edge"),
        (pf86 / "Microsoft" / "Edge" / "Application", "edge"),
    ]


def _file_version(path: Path) -> str:
    """Read the real product version out of the executable."""
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, data):
            return ""
        buf = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(
            data, "\\", ctypes.byref(buf), ctypes.byref(length)
        ):
            return ""

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD), ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        info = ctypes.cast(buf, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return ""


def find_browser() -> tuple[str | None, str | None, str]:
    """Return (exe path, kind, full version) for an installed Chromium browser."""
    for base, kind in _install_dirs():
        if not base.exists():
            continue
        exe_name = "chrome.exe" if kind == "chrome" else "msedge.exe"
        plain = base / exe_name
        if plain.exists():
            return str(plain), kind, _file_version(plain)
        # some installs keep the binary in a versioned subfolder
        try:
            for d in base.iterdir():
                cand = d / exe_name
                if d.is_dir() and d.name[:1].isdigit() and cand.exists():
                    return str(cand), kind, _file_version(cand)
        except OSError:
            pass
    return None, None, ""


def _profile_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "ProxyRotator" / "profiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _prune(root: Path, keep: int = _MAX_PROFILES) -> None:
    """Keep the profile folder from growing without bound."""
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime)
        for old in dirs[:-keep]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def make_fingerprint() -> dict:
    exe, kind, version = find_browser()
    if not exe:
        raise RuntimeError("No Chrome or Edge found on this system")
    major = (version.split(".")[0] if version else "131")
    w, h = random.choice(_RESOLUTIONS)
    lang = random.choice(_LANGS)

    if kind == "edge":
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
    else:
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")

    return {"exe": exe, "browser": kind, "version": version or major,
            "user_agent": ua, "window": [w, h], "lang": lang}


def launch(proxy_addr: str, start_url: str = "https://api.ipify.org") -> dict:
    fp = make_fingerprint()
    root = _profile_root()
    _prune(root)
    profile = root / uuid.uuid4().hex[:12]
    profile.mkdir(parents=True, exist_ok=True)

    w, h = fp["window"]
    args = [
        fp["exe"],
        f"--proxy-server=http://{proxy_addr}",
        f"--user-data-dir={profile}",
        f"--user-agent={fp['user_agent']}",
        f"--window-size={w},{h}",
        f"--lang={fp['lang']}",
        # keep WebRTC from leaking the real address outside the proxy
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        start_url,
    ]
    subprocess.Popen(args, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

    fp_out = {
        "browser": fp["browser"],
        "version": fp["version"],
        "user_agent": fp["user_agent"],
        "window": f"{w}x{h}",
        "lang": fp["lang"],
        "profile": str(profile),
        "opened_at": time.time(),
    }
    try:
        (profile / "fingerprint.json").write_text(json.dumps(fp_out, indent=2), encoding="utf-8")
    except OSError:
        pass
    return fp_out
