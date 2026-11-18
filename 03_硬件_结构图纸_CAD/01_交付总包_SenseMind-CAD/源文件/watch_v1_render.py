#!/usr/bin/env python3
"""把 STL 渲染成能直接看的 PNG (平板着色 + 画家算法, 不需要 CAD/查看器).

用法:
  python watch_v1_render.py            # 读当前目录或 out/ 下的 STL, 输出到 01_预览图/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SRC = HERE / "out" if (HERE / "out").exists() else HERE
DST = (HERE / "01_预览图") if (HERE / "01_预览图").exists() else (HERE.parent / "预览图")

# 零件配色 (R,G,B)
COLORS = {
    "body": (214, 219, 226),
    "bezel": (47, 53, 66),
    "back_cover": (176, 183, 192),
    "sensor_carrier": (110, 200, 160),
    "battery_bay": (245, 185, 66),
    "usbc_end_cap": (86, 96, 111),
    "button_caps": (255, 107, 129),
}
# 爆炸偏移 (沿 Z, mm)
EXPLODE = {
    "back_cover": -34.0, "battery_bay": -21.0, "sensor_carrier": -11.0,
    "body": 4.0, "bezel": 17.0, "usbc_end_cap": 4.0, "button_caps": 4.0,
}

LIGHT = np.array([-0.45, -0.55, 0.70])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
VIEW = np.array([0.85, -0.95, 0.80])       # 视点方向 (从 +X,-Y,+Z 看)
VIEW = VIEW / np.linalg.norm(VIEW)


def basis():
    up = np.array([0.0, 0.0, 1.0])
    u = np.cross(up, VIEW)
    u = u / np.linalg.norm(u)
    v = np.cross(VIEW, u)
    v = v / np.linalg.norm(v)
    return u, v


def load_parts():
    parts = []
    for name, color in COLORS.items():
        f = SRC / f"watch_v1_{name}.stl"
        if not f.exists():
            print("missing", f)
            continue
        mesh = trimesh.load(f, force="mesh")
        parts.append((name, color, mesh))
    return parts


DRAW_ORDER = ["back_cover", "battery_bay", "sensor_carrier", "body",
              "bezel", "usbc_end_cap", "button_caps"]


def _tris(name, color, mesh, explode, u, v, offset):
    verts = np.asarray(mesh.vertices, dtype=np.float64).copy()
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if explode:
        verts[:, 2] += EXPLODE.get(name, 0.0)
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln < 1e-12] = 1.0
    n = n / ln
    keep = (n @ VIEW) > 1e-6            # 背面剔除
    tri, n = tri[keep], n[keep]
    lam = np.abs(n @ LIGHT)
    shade = 0.34 + 0.66 * lam
    base = np.array(color, dtype=np.float64) / 255.0
    rgb = np.clip(base[None, :] * shade[:, None], 0, 1)
    p2 = np.stack([tri @ u, tri @ v], axis=-1) + offset
    depth = tri.mean(axis=1) @ VIEW
    return p2, rgb, depth


def render(parts, explode, out_path, size=(2200, 1650), ss=2):
    u, v = basis()
    order = [n for n in DRAW_ORDER if any(p[0] == n for p in parts)]
    order += [p[0] for p in parts if p[0] not in DRAW_ORDER]

    # 统一取景
    allp = []
    per = {}
    for name in order:
        _, color, mesh = next(p for p in parts if p[0] == name)
        p2, rgb, depth = _tris(name, color, mesh, explode, u, v, np.zeros(2))
        per[name] = (p2, rgb, depth)
        allp.append(p2.reshape(-1, 2))
    allp = np.concatenate(allp)
    mn, mx = allp.min(0), allp.max(0)

    W, H = size[0] * ss, size[1] * ss
    scale = min((W * 0.86) / (mx[0] - mn[0]), (H * 0.86) / (mx[1] - mn[1]))
    cx, cy = (mn + mx) / 2
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    for name in order:                      # 按装配层级顺序画，避免共面闪烁
        p2, rgb, depth = per[name]
        sx = (p2[..., 0] - cx) * scale + W / 2
        sy = -(p2[..., 1] - cy) * scale + H / 2
        for i in np.argsort(depth):         # 同一零件内部仍按深度
            pts = [(sx[i, k], sy[i, k]) for k in range(3)]
            c = tuple(int(round(x * 255)) for x in rgb[i])
            draw.polygon(pts, fill=c)

    img = img.resize(size, Image.LANCZOS)
    img.save(out_path, quality=95)
    print("wrote", out_path, img.size)


def main():
    DST.mkdir(parents=True, exist_ok=True)
    parts = load_parts()
    if not parts:
        raise SystemExit("没找到 STL")
    render(parts, False, DST / "00_装配体全貌.png")
    render(parts, True, DST / "01_爆炸图.png")
    # 单件
    order = ["body", "bezel", "back_cover", "sensor_carrier",
             "battery_bay", "usbc_end_cap", "button_caps"]
    for i, name in enumerate(order, start=2):
        one = [p for p in parts if p[0] == name]
        if one:
            render(one, False, DST / f"{i:02d}_{name}.png", size=(1400, 1050))


if __name__ == "__main__":
    main()
