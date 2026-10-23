"""Временная проба: какие формы пути unix-сокета понимает xray на Windows."""

import json
import os
import subprocess
import sys
import tempfile
import time

xray = sys.argv[1]
for listen_style in ("native", "forward"):
    directory = tempfile.mkdtemp(prefix="tenga-probe-", dir=os.environ.get("LOCALTEMP"))
    native = os.path.join(directory, "stats.sock").replace("/", "\\")
    listen = native if listen_style == "native" else native.replace("\\", "/")
    config = {
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService"]},
        "policy": {"system": {"statsOutboundUplink": True}},
        "inbounds": [
            {
                "tag": "api",
                "listen": listen,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "tag": "proxy"}],
        "routing": {"rules": [{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}]},
    }
    source = os.path.join(directory, "config.json")
    with open(source, "w") as f:
        json.dump(config, f)
    proc = subprocess.Popen([xray, "run", "-c", source], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(2)
    print(f"== listen={listen!r} exists={os.path.exists(native)} alive={proc.poll() is None}")
    forward = native.replace("\\", "/")
    for server in (
        f"unix://{forward}",
        f"unix:{forward}",
        f"unix:{native}",
        f"unix:///{forward}",
        f"unix://{native}",
    ):
        r = subprocess.run([xray, "api", "statsquery", f"--server={server}"], capture_output=True, text=True, timeout=10)
        print(f"   {server!r}: rc={r.returncode} {(r.stderr or r.stdout).strip()[:120]}")
    proc.terminate()
    out = proc.communicate(timeout=5)[0].decode(errors="replace")
    print("   xray output:", out.strip()[-400:])
