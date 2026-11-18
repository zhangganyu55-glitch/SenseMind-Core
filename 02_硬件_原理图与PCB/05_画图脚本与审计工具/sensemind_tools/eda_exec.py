#!/usr/bin/env python3
"""Execute a JS snippet in the running EasyEDA Pro via the bridge.

Usage: python3 eda_exec.py snippet.js
The snippet must be the body of an async function receiving `eda`.
"""
import json
import sys
import urllib.request

PORT = 49620
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def execute(code):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/execute" % PORT,
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    if len(sys.argv) < 2:
        print("usage: eda_exec.py <file.js>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        code = fh.read()
    out = execute(code)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
