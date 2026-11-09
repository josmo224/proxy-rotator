"""Prove manual mode auto-fails over from a dead proxy to a working one."""
import json, subprocess, sys, time, urllib.request, socket
sys.path.insert(0, ".")
import test_rotator as T

ORIGIN, GOOD, ROT = 18081, 18082, 18100
T.serve(ORIGIN, T.Origin)
T.serve(GOOD, T.FakeProxy, tag="A")

# first proxy is dead (nothing listens on 127.0.0.1:9), second works
open("_fail.txt", "w").write(f"127.0.0.1:9\n127.0.0.1:{GOOD}\n")
proc = subprocess.Popen(
    [sys.executable, "rotator.py", "--proxies", "_fail.txt", "--port", str(ROT),
     "--status-port", "0", "--mode", "manual", "--no-check", "--no-hotkey", "-v",
     "--used-file", "_u.txt", "--current-file", "_c.txt", "--reset-used"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    assert T.wait_port(ROT), "rotator did not start"
    print("current at start:", "127.0.0.1:9 (dead)")
    op = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": f"http://127.0.0.1:{ROT}", "https": f"http://127.0.0.1:{ROT}"}))
    with op.open(f"http://127.0.0.1:{ORIGIN}/", timeout=20) as r:
        body = r.read().decode()
    print("request through dead-first rotator ->", body)
    assert "used=A" in body, body
    print("PASS: request auto-failed over to the working proxy")
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    if out.strip():
        print("--- rotator log ---\n" + out.strip()[-800:])
    for f in ("_fail.txt", "_u.txt", "_c.txt"):
        try:
            __import__("os").remove(f)
        except OSError:
            pass
