"""
fingerprint.py - coherent per-session browser identity.

A profile alone does not change the device fingerprint: canvas rendering, WebGL
vendor/renderer, audio processing, CPU/memory counts and platform all stay the
same. This module generates a random-but-internally-consistent identity and
injects overrides into the page before any script runs, over the DevTools
protocol.

Every launch gets one identity; within that browser all values agree with each
other (a "Windows / NVIDIA" machine never reports an Apple GPU, etc.).
"""
from __future__ import annotations

import base64
import json
import os
import random
import struct
import time
import urllib.request

# ---------- identity generation -------------------------------------------

_RESOLUTIONS = [
    (1920, 1080), (1536, 864), (1600, 900), (1366, 768),
    (1440, 900), (1680, 1050), (1280, 720), (2560, 1440),
]
_LANGS = [("en-US", "en-US"), ("en-GB", "en-GB"), ("en-US", "en-US")]
_CPUS = [4, 6, 8, 8, 12, 16]
_MEM = [4, 8, 8, 8, 16, 16]
# (vendor, renderer) pairs that occur together on real Windows machines
_GPUS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]


def make(version: str, kind: str) -> dict:
    major = version.split(".")[0] if version else "131"
    w, h = random.choice(_RESOLUTIONS)
    lang, accept = random.choice(_LANGS)
    vendor, renderer = random.choice(_GPUS)
    if kind == "edge":
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")
    else:
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    seed = random.getrandbits(32)
    rnd = random.Random(seed)
    return {
        "seed": seed,
        "user_agent": ua,
        "major": major,
        "kind": kind,
        "version": version or major,
        "platform": "Win32",
        "window": [w, h],
        "screen": [w, h],
        "color_depth": 24,
        "hardware_concurrency": random.choice(_CPUS),
        "device_memory": random.choice(_MEM),
        "lang": lang,
        "accept_language": accept,
        "languages": [lang, accept] if lang != accept else [lang, "en"],
        "webgl_vendor": vendor,
        "webgl_renderer": renderer,
        "canvas_noise": [rnd.randint(1, 3) for _ in range(16)],
        "audio_noise": [round(rnd.uniform(-2e-7, 2e-7), 12) for _ in range(32)],
    }


def inject_js(fp: dict) -> str:
    data = json.dumps({
        "hc": fp["hardware_concurrency"],
        "dm": fp["device_memory"],
        "platform": fp["platform"],
        "languages": fp["languages"],
        "sw": fp["screen"][0],
        "sh": fp["screen"][1],
        "depth": fp["color_depth"],
        "gv": fp["webgl_vendor"],
        "gr": fp["webgl_renderer"],
        "cn": fp["canvas_noise"],
        "an": fp["audio_noise"],
    })
    return r"""
(() => {
  const FP = %s;
  const def = (obj, prop, value) => {
    try { Object.defineProperty(obj, prop, {get: () => value, configurable: true}); } catch (e) {}
  };

  // --- navigator ---------------------------------------------------------
  def(Navigator.prototype, 'hardwareConcurrency', FP.hc);
  def(Navigator.prototype, 'deviceMemory', FP.dm);
  def(Navigator.prototype, 'platform', FP.platform);
  def(Navigator.prototype, 'languages', Object.freeze(FP.languages.slice()));
  def(Navigator.prototype, 'webdriver', false);

  // --- screen ------------------------------------------------------------
  def(Screen.prototype, 'width', FP.sw);
  def(Screen.prototype, 'height', FP.sh);
  def(Screen.prototype, 'availWidth', FP.sw);
  def(Screen.prototype, 'availHeight', FP.sh - 40);
  def(Screen.prototype, 'colorDepth', FP.depth);
  def(Screen.prototype, 'pixelDepth', FP.depth);

  // --- WebGL vendor / renderer ------------------------------------------
  const patchGL = (proto) => {
    if (!proto || !proto.getParameter) return;
    const orig = proto.getParameter;
    proto.getParameter = function (p) {
      if (p === 37445) return FP.gv;   // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return FP.gr;   // UNMASKED_RENDERER_WEBGL
      return orig.call(this, p);
    };
    const origExt = proto.getExtension;
    if (origExt) {
      proto.getExtension = function (name) {
        const ext = origExt.call(this, name);
        if (name === 'WEBGL_debug_renderer_info' && ext) {
          try {
            ext.UNMASKED_VENDOR_WEBGL = 37445;
            ext.UNMASKED_RENDERER_WEBGL = 37446;
          } catch (e) {}
        }
        return ext;
      };
    }
  };
  patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // --- canvas noise (deterministic for this session) ---------------------
  // Perturb OPAQUE pixels: touching alpha=0 pixels does not change the PNG.
  const noisePixels = (data, cn) => {
    let touched = 0;
    for (let i = 0; i < data.length && touched < cn.length; i += 4) {
      if (data[i + 3] > 0) {
        data[i] = (data[i] + cn[touched]) & 255;
        touched++;
      }
    }
    return touched;
  };

  const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function (...a) {
    const d = origGetImageData.apply(this, a);
    try { noisePixels(d.data, FP.cn); } catch (e) {}
    return d;
  };

  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function (...a) {
    try {
      const ctx = this.getContext('2d');
      if (ctx && this.width && this.height) {
        const img = origGetImageData.call(ctx, 0, 0, this.width, this.height);
        if (noisePixels(img.data, FP.cn)) ctx.putImageData(img, 0, 0);
      }
    } catch (e) {}
    return origToDataURL.apply(this, a);
  };

  const origToBlob = HTMLCanvasElement.prototype.toBlob;
  if (origToBlob) {
    HTMLCanvasElement.prototype.toBlob = function (cb, ...rest) {
      try {
        const ctx = this.getContext('2d');
        if (ctx && this.width && this.height) {
          const img = origGetImageData.call(ctx, 0, 0, this.width, this.height);
          if (noisePixels(img.data, FP.cn)) ctx.putImageData(img, 0, 0);
        }
      } catch (e) {}
      return origToBlob.call(this, cb, ...rest);
    };
  }

  // --- audio noise -------------------------------------------------------
  if (window.AnalyserNode) {
    const origAFD = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function (arr) {
      origAFD.call(this, arr);
      try {
        for (let i = 0; i < arr.length; i++) arr[i] += FP.an[i %% FP.an.length];
      } catch (e) {}
    };
  }
})();
""" % data


# ---------- tiny WebSocket client for CDP ---------------------------------

class _WS:
    def __init__(self, url: str, timeout: float = 20.0):
        rest = url.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        host, port = hostport.rsplit(":", 1)
        self.sock = __import__("socket").create_connection((host, int(port)), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            self.buf += chunk
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"websocket rejected: {head[:80]!r}")

    def _send(self, payload: bytes) -> None:
        header = bytearray([0x81])
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> dict:
        while True:
            b1, b2 = self._read(2)
            op = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length) if length else b""
            if op == 0x9:                     # ping
                self.sock.sendall(b"\x8a\x00")
                continue
            if op == 0x8:                     # close
                raise ConnectionError("websocket closed")
            if op in (0x1, 0x2):
                return json.loads(payload.decode("utf-8", "replace"))

    def call(self, mid: int, method: str, params: dict | None = None) -> dict:
        self._send(json.dumps({"id": mid, "method": method,
                               "params": params or {}}).encode())
        deadline = time.time() + 10
        while time.time() < deadline:
            msg = self.recv()
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(f"no response for {method}")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def _debug_ws_url(port: int, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last_page = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=2
            ) as r:
                targets = json.loads(r.read())
            pages = [t for t in targets
                     if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                # prefer the blank tab we opened, not an extension page
                for p in pages:
                    if p.get("url", "").startswith("about:"):
                        return p["webSocketDebuggerUrl"]
                last_page = pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        if last_page and time.time() > deadline - 5:
            return last_page
        time.sleep(0.15)
    if last_page:
        return last_page
    raise TimeoutError("DevTools endpoint not ready")


def apply(port: int, fp: dict, start_url: str, attempts: int = 3) -> None:
    """Attach over CDP and install the identity before the first navigation."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            _apply_once(port, fp, start_url)
            return
        except Exception as exc:  # noqa: BLE001 - retry startup races
            last = exc
            time.sleep(0.8)
    if last is not None:
        raise last


def _apply_once(port: int, fp: dict, start_url: str) -> None:
    ws = _WS(_debug_ws_url(port))
    try:
        ws.call(1, "Page.enable")
        ws.call(2, "Runtime.enable")
        ws.call(3, "Emulation.setUserAgentOverride", {
            "userAgent": fp["user_agent"],
            "acceptLanguage": fp["accept_language"],
            "platform": fp["platform"],
            "userAgentMetadata": {
                "brands": [
                    {"brand": "Chromium", "version": fp["major"]},
                    {"brand": "Google Chrome", "version": fp["major"]},
                    {"brand": "Not?A_Brand", "version": "24"},
                ],
                "fullVersion": fp["version"],
                "platform": "Windows",
                "platformVersion": "10.0.0",
                "architecture": "x86",
                "model": "",
                "mobile": False,
            },
        })
        ws.call(4, "Emulation.setDeviceMetricsOverride", {
            "width": fp["window"][0],
            "height": fp["window"][1],
            "deviceScaleFactor": 1,
            "mobile": False,
            "screenWidth": fp["screen"][0],
            "screenHeight": fp["screen"][1],
        })
        ws.call(5, "Page.addScriptToEvaluateOnNewDocument",
                {"source": inject_js(fp)})
        ws.call(6, "Page.navigate", {"url": start_url})
    finally:
        ws.close()
