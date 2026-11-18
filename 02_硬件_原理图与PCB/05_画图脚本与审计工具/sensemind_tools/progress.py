#!/usr/bin/env python3
"""Update the SenseMind progress dashboard state.

Usage:
  python3 progress.py phase "文本"
  python3 progress.py item "页/任务名" ok|work|wait|bad "备注"
  python3 progress.py log "一行日志"
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "progress.json")


def load():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"phase": "", "items": [], "log": [], "agent": "DSH · EasyEDA bridge",
                "updated": ""}


def save(s):
    s["updated"] = time.strftime("%H:%M:%S")
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(s, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    s = load()
    if cmd == "phase" and len(sys.argv) > 2:
        s["phase"] = sys.argv[2]
    elif cmd == "item" and len(sys.argv) > 3:
        name, status = sys.argv[2], sys.argv[3]
        note = sys.argv[4] if len(sys.argv) > 4 else ""
        for it in s["items"]:
            if it["name"] == name:
                it["status"], it["note"] = status, note
                break
        else:
            s["items"].append({"name": name, "status": status, "note": note})
    elif cmd == "log" and len(sys.argv) > 2:
        s["log"].insert(0, "<b>%s</b>  %s" % (time.strftime("%H:%M:%S"), sys.argv[2]))
        s["log"] = s["log"][:40]
    else:
        print(__doc__)
        return 2
    save(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
