#!/usr/bin/env python3
"""把 测量记录表.csv 里的实测值写回 watch_v1_params.json，并重算厚度堆叠 + 干涉检查。

用法：
    1. 在 测量记录表.csv 的「采用值」列填数字（只填这一列）
    2. python3 apply_measurements.py            # 干跑，只看差异
       python3 apply_measurements.py --write    # 真正写回 json
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PARAMS = HERE / "watch_v1_params.json"
CSV = HERE / "测量记录表.csv"


def read_measurements():
    rows = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            key = (r.get("参数键") or "").strip()
            raw = (r.get("采用值") or "").strip()
            if not key or key.startswith("(") or not raw:
                continue
            try:
                val = float(raw)
            except ValueError:
                print(f"!! {r['编号']} 采用值不是数字: {raw!r}，跳过")
                continue
            rows.append((r["编号"], r["项目"], key, val))
    return rows


def main():
    write = "--write" in sys.argv
    data = json.loads(PARAMS.read_text(encoding="utf-8"))
    P, M = data["params"], data["meta"]

    rows = read_measurements()
    if not rows:
        print("测量记录表.csv 的「采用值」列还是空的——先填数字再来。")
        return 1

    print(f"{'编号':5s} {'参数':12s} {'原值':>8s} {'实测':>8s} {'Δ':>8s}  项目")
    changed = 0
    for mid, name, key, val in rows:
        old = P.get(key)
        if old is None:
            print(f"!! {mid} 参数 {key} 不存在，跳过")
            continue
        d = val - old
        flag = "" if abs(d) < 1e-9 else " *"
        print(f"{mid:5s} {key:12s} {old:8.2f} {val:8.2f} {d:+8.2f}{flag}  {name}")
        if abs(d) > 1e-9:
            changed += 1
        P[key] = val
        meta = M.setdefault(key, {})
        meta["status"] = "measured"
        meta["source"] = f"游标卡尺实测 {date.today().isoformat()}"
        prev = meta.get("notes") or ""
        if "实测" not in prev:
            meta["notes"] = (prev + " / " if prev else "") + f"实测值 {val:g}"

    # ---- 厚度堆叠 ----
    import importlib

    import watch_v1_cad as W

    importlib.reload(W)
    D = W.derive(P)

    stack = [
        ("表圈 bezel_t", P["bezel_t"]),
        ("前面板 front_t", P["front_t"]),
        ("屏前隙 disp_front_gap", P["disp_front_gap"]),
        ("屏幕 disp_t", P["disp_t"]),
        ("板隙 board_gap", P["board_gap"]),
        ("排针 hdr_h", P["hdr_h"]),
        ("主板 board_t", P["board_t"]),
        ("电池隙 bat_gap", P["bat_gap"]),
        ("电池 bat_t", P["bat_t"]),
        ("泡棉 bat_foam", P["bat_foam"]),
        ("下盖 back_t", P["back_t"]),
    ]
    print("\n厚度堆叠：")
    acc = 0.0
    for name, v in stack:
        acc += v
        print(f"  {name:24s} {v:6.2f}   累计 {acc:6.2f}")
    print(f"  {'合计':24s} {D['total']:6.2f} mm")

    over = D["total"] - 24.0
    if over > 0:
        print(f"\n⚠️ 总厚 {D['total']:.2f} 超过 24 mm 目标 {over:+.2f} mm —— 需要减薄（去排针 / 换 FPC 屏 / 减泡棉）")
    else:
        print(f"\n✅ 总厚 {D['total']:.2f} mm，在 24 mm 以内（余 {-over:.2f} mm）")

    # 电池可用空间
    spare = D["inner_floor"] - D["bat_bot"]
    print(f"电池区底部余量 {spare:+.2f} mm")
    if spare < 0:
        print("⚠️ 电池顶到内腔底 —— 减薄电池、减泡棉或加长壳体")

    if write:
        PARAMS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写回 {PARAMS}（{changed} 项更新）")
    else:
        print(f"\n[干跑] {changed} 项会更新；加 --write 真正写回")

    # ---- 干涉检查 ----
    print("\n干涉检查（仅结构件 + 电子件占位）：")
    import watch_v1_electronics as E

    parts = {
        "body": W.build_body(P, D),
        "back_cover": W.build_back_cover(P, D),
        "sensor_carrier": W.build_sensor_carrier(P, D),
        "battery_bay": W.build_battery_bay(P, D),
    }
    for name, (solid, _mat, _desc) in E.build_electronics(P, D).items():
        parts[name] = solid

    def vol(s):
        if s is None:
            return 0.0
        if hasattr(s, "volume"):
            try:
                return s.volume
            except Exception:
                pass
        try:
            return sum(x.volume for x in s)
        except Exception:
            return 0.0

    boxes = {k: v.bounding_box() for k, v in parts.items()}
    names = sorted(parts)
    hits = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ba, bb = boxes[a], boxes[b]
            if (ba.min.X > bb.max.X or bb.min.X > ba.max.X or
                    ba.min.Y > bb.max.Y or bb.min.Y > ba.max.Y or
                    ba.min.Z > bb.max.Z or bb.min.Z > ba.max.Z):
                continue
            v = vol(parts[a].intersect(parts[b]))
            if v > 0.5:
                hits.append((a, b, v))

    if not hits:
        print("  ✅ 无干涉")
    else:
        total = sum(h[2] for h in hits)
        for a, b, v in sorted(hits, key=lambda x: -x[2]):
            print(f"  ⚠️ {a:16s} × {b:16s} {v:8.2f} mm³")
        print(f"  合计 {len(hits)} 处 / {total:.2f} mm³（小于 5 mm³ 的多半是贴合面数值噪声）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
