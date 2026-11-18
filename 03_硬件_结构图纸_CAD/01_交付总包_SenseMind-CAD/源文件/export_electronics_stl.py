#!/usr/bin/env python3
"""导出电子件占位体 STL（供 Blender 渲染/爆炸图用），命名 watch_v1_el_<name>.stl"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build123d import export_stl  # noqa: E402

import watch_v1_cad as W  # noqa: E402
import watch_v1_electronics as E  # noqa: E402

P, _ = W.load_params()
D = W.derive(P)
out = HERE / "out"
out.mkdir(parents=True, exist_ok=True)

for name, (solid, _mat, _desc) in E.build_electronics(P, D).items():
    path = out / f"watch_v1_el_{name}.stl"
    export_stl(solid, str(path), tolerance=0.03, angular_tolerance=0.2)
    bb = solid.bounding_box()
    print(f"  el_{name:12s} {bb.size.X:6.1f} x {bb.size.Y:6.1f} x {bb.size.Z:5.1f}")
print("done ->", out)
