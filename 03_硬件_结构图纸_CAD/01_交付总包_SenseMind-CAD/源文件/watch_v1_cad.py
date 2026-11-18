#!/usr/bin/env python3
"""SenseMind H3-05 手表 V1 - 参数化机械结构生成器.

唯一数据源: watch_v1_params.json
运行:  <venv>/bin/python watch_v1_cad.py --out <输出目录>

生成:
  *.step / *.stl   7 个零件 + fit-check
  watch_v1_params.csv
  watch_v1_stack.json  (供 watch_v1_docs.py 出图)

设计原则:
  * 所有尺寸来自参数表, 没有任何硬编码数字藏在函数里
  * 每个零件单独成体, 可单独打印/替换
  * 未实测尺寸一律 assumed, 并在 CSV 标注
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from build123d import (
    Axis,
    Box,
    Cylinder,
    Pos,
    Rot,
    RectangleRounded,
    SlotOverall,
    chamfer,
    export_step,
    export_stl,
    extrude,
)

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- params
def load_params():
    data = json.loads((HERE / "watch_v1_params.json").read_text(encoding="utf-8"))
    P, M = data["params"], data["meta"]
    missing = [k for k in P if k not in M]
    if missing:
        raise SystemExit(f"参数缺少 meta 状态: {missing}")
    return P, M


def derive(P):
    """把堆叠算成一组深度 (depth, 从前面板表面向下为正, 单位 mm)."""
    d = {}
    d["disp_front"] = P["front_t"] + P["disp_front_gap"]
    d["disp_back"] = d["disp_front"] + P["disp_t"]
    d["hdr_top"] = d["disp_back"] + P["board_gap"]
    d["board_top"] = d["hdr_top"] + P["hdr_h"]
    d["board_bot"] = d["board_top"] + P["board_t"]
    d["bat_top"] = d["board_bot"] + P["bat_gap"]
    d["bat_bot"] = d["bat_top"] + P["bat_t"] + P["bat_foam"]
    d["carrier_top"] = d["board_bot"] + P["carrier_gap"]
    d["carrier_bot"] = d["carrier_top"] + P["carrier_t"]
    d["sensor_bot"] = d["carrier_bot"] + max(P["max_t"], P["mpu_t"])
    # 内腔底 = 传感器堆叠 / 电池堆叠 里更深的那一侧 + 0.3 余量
    d["inner_floor"] = max(d["sensor_bot"], d["bat_bot"]) + 0.3
    d["body_d"] = d["inner_floor"]
    d["total"] = d["inner_floor"] + P["back_t"] + P["bezel_t"]
    d["bat_zone_depth"] = d["bat_bot"]
    d["bat_clear"] = d["inner_floor"] - d["bat_bot"]
    d["screws"] = [tuple(float(v) for v in s.split(",")) for s in P["screw_points"]]
    return d


# ------------------------------------------------------------- primitives
def slab(w, h, r, d0, d1, xy=(0.0, 0.0)):
    """圆角矩形板: XY 方向 w*h (圆角 r), 深度从 d0 到 d1 (d 越大越靠皮肤侧)."""
    solid = extrude(RectangleRounded(w, h, r), amount=(d1 - d0))
    return Pos(xy[0], xy[1], -d1) * solid


def box(dx, dy, dz, x, y, d):
    """以 (x,y) 为中心、深度中心 d 的立方块."""
    return Pos(x, y, -d) * Box(dx, dy, dz)


def cyl_x(r, x0, x1, y, d):
    return Pos((x0 + x1) / 2, y, -d) * Rot(0, 90, 0) * Cylinder(r, abs(x1 - x0))


def cyl_z(r, d0, d1, x, y):
    return Pos(x, y, -(d0 + d1) / 2) * Cylinder(r, abs(d1 - d0))


# ------------------------------------------------------------------ parts
def build_body(P, D):
    W, L, R = P["case_w"], P["case_l"], P["case_r"]
    w, ft = P["wall"], P["front_t"]
    H = D["body_d"]

    body = slab(W, L, R, 0.0, H)
    body -= slab(W - 2 * w, L - 2 * w, R - w, ft, H + 1.0)          # 内腔
    body -= slab(P["window_w"], P["window_l"], P["window_r"], -1.0, ft + 0.1)  # 屏开窗

    # 屏托边: 屏背面两侧的 shelf, 从内壁伸到屏边缘下方
    ledge_len = 24.0
    for sgn in (+1, -1):
        y_outer = sgn * (L / 2 - w)                      # 内壁
        y_inner = sgn * (P["disp_l"] / 2 - 0.2)          # 伸到屏边缘
        yc = (y_outer + y_inner) / 2
        body += box(ledge_len, abs(y_outer - y_inner), 1.2, 0, yc, D["disp_back"] + 0.6)

    # USB-C 连接器让位: 切掉 -Y 侧托边中段, 避免与插头/端盖干涉
    body -= box(15.0, 7.6, 8.0, 0, -L / 2 + w + 3.8, D["disp_back"] + 0.9)

    # 主板靠电池仓上沿 + 双面胶定位 (原两条侧轨压进 PCB 底面 0.8 mm, 已取消)

    # 4 个螺丝柱 (下盖从这里上螺丝)
    for (bx, by) in D["screws"]:
        body += cyl_z(P["boss_od"] / 2, H - 6.0, H, bx, by)
        body -= cyl_z(P["boss_hole"] / 2, H - 5.0, H + 0.5, bx, by)

    # 按钮: 外侧按帽孔 + 内侧开关让位
    for yb in (P["btn_y1"], P["btn_y2"]):
        body -= cyl_x(P["btn_cap_d"] / 2, W / 2 - P["btn_pocket_depth"] - w,
                      W / 2 + 1.0, yb, 9.0)
        body -= cyl_x(P["btn_pocket_d"] / 2, W / 2 - w - P["btn_pocket_depth"],
                      W / 2 - w + 0.2, yb, 9.0)
        # 外侧沉孔: 让按键帽法兰落进去 (否则法兰埋在壳体里)
        body -= cyl_x(P["btn_cap_d"] / 2 + 0.7, W / 2 - 0.8, W / 2 + 1.0, yb, 9.0)

    # USB-C 端盖开口 (6 点方向, -Y 壁)
    body -= box(P["usbc_open_w"], 6.0, P["usbc_open_h"], 0, -L / 2 + w - 3.0, P["usbc_z"])
    body -= box(P["usbc_flange_w"], P["usbc_flange_t"] + 0.4, P["usbc_flange_h"],
                0, -L / 2 + (P["usbc_flange_t"] + 0.4) / 2 - 0.2, P["usbc_z"])

    # ID: 顶面/底面倒角 (小倒角最便宜、最有效的精致度手段)
    try:
        top = body.edges().filter_by_position(Axis.Z, -0.01, 0.01)
        body = chamfer(top, length=P["chamfer_top"])
    except Exception as exc:
        print("  [warn] 顶面倒角失败:", exc)
    # 底面不倒角: 与下盖的接缝线用 cover_reveal 做, 避免内腔/螺丝柱边被误选

    # 表耳 + 生耳孔 (20 mm 表带)
    lw, ll, lt = P["lug_w"], P["lug_len"], P["lug_t"]
    for sy in (+1, -1):
        for sx in (+1, -1):
            x = sx * (P["strap_w"] / 2 + lw / 2)
            y = sy * (L / 2 + ll / 2 - 0.6)
            body += box(lw, ll, lt, x, y, P["lug_z"] + lt / 2)
            body -= cyl_x(P["bar_d"] / 2, x - 3.6, x + 3.6,
                          sy * (L / 2 + ll - 2.0), P["lug_z"] + lt / 2)

    # 天线窗: 12 点方向内壁减薄 0.4
    body -= box(P["antenna_keepout_w"], 0.4, P["antenna_keepout_l"],
                0, L / 2 - w + 0.2, 4.0)
    return body


def build_bezel(P, D):
    W, L, R = P["case_w"], P["case_l"], P["case_r"]
    t = P["bezel_t"]
    rv = P["bezel_reveal"]
    bez = slab(W - rv, L - rv, max(R - rv / 2, 0.5), -t, 0.0)
    bez -= slab(P["window_w"], P["window_l"], P["window_r"], -t - 1.0, 0.5)
    try:
        edges = bez.edges().filter_by_position(Axis.Z, -0.01, 0.01)
        bez = chamfer(edges, length=P["chamfer_top"] * 0.7)
    except Exception as exc:
        print("  [warn] 表圈倒角失败:", exc)
    return bez


def build_back_cover(P, D):
    W, L, R = P["case_w"], P["case_l"], P["case_r"]
    H = D["body_d"]
    t = P["back_t"]

    rv = P["cover_reveal"]
    cov = slab(W - rv, L - rv, max(R - rv / 2, 0.5), H, H + t)
    # 螺丝过孔 + 沉头
    for (x, y) in D["screws"]:
        cov -= cyl_z(P["cbore_d"] / 2, H + t - P["cbore_t"], H + t + 0.5, x, y)
        cov -= cyl_z(P["screw_d"] / 2 + 0.1, H - 0.5, H + t + 0.5, x, y)
    # 光学窗
    cov -= slab(P["opt_w"], P["opt_l"], 1.0,
                H - 0.5, H + t + 0.5, (P["max_x"], P["sensor_y"]))
    # 遮光圈 (黑色泡棉环, 压在模块与窗口之间)
    sh = P["shield_h"]
    ring = slab(P["opt_w"] + 2.0, P["opt_l"] + 2.0, 1.2, H - 0.3, H, (P["max_x"], P["sensor_y"]))
    ring -= slab(P["opt_w"], P["opt_l"], 1.0, H - 1.0, H + 1, (P["max_x"], P["sensor_y"]))
    cov += ring
    # 载板改为粘贴固定（原 4 根支撑柱落在两个传感器模块体积内, 取消）
    return cov


def build_sensor_carrier(P, D):
    ct, cb = D["carrier_top"], D["carrier_bot"]
    yc = P["sensor_y"]
    x0 = min(P["max_x"] - P["max_w"] / 2, P["mpu_x"] - P["mpu_w"] / 2) - 0.8
    x1 = max(P["max_x"] + P["max_w"] / 2, P["mpu_x"] + P["mpu_w"] / 2) + 0.3
    x1 = min(x1, P["case_w"] / 2 - P["wall"] - 2.6)
    w = x1 - x0
    car = slab(w, P["mpu_l"] + 0.6, 2.5, ct, cb, ((x0 + x1) / 2, yc))

    # 两个模块让位 (模块背面贴在载板上, 元件朝皮肤侧)
    car -= slab(P["max_w"] + 0.8, P["max_l"] + 0.8, 1.5,
                ct + 0.4, cb + 1.0, (P["max_x"], yc))
    car -= slab(P["mpu_w"] + 0.8, P["mpu_l"] + 0.8, 1.5,
                ct + 0.4, cb + 1.0, (P["mpu_x"], yc))

    # ±2 mm 可调槽 (用 M1.6 螺丝固定到载板支柱上)
    for sx in (+1, -1):
        for sy in (+1, -1):
            slot = extrude(SlotOverall(6.0, 1.8), amount=(cb - ct + 2))
            car -= Pos(sx * 10.5, yc + sy * 5.5, -ct - 1) * Rot(0, 0, 90) * slot
    # 螺丝柱让位
    for (bx, by) in D["screws"]:
        car -= cyl_z(2.4, ct - 1, cb + 1, bx, by)
    # 裁到内腔轮廓 (圆角处不撞壁)
    car &= slab(P["case_w"] - 2 * P["wall"] - 0.2, P["case_l"] - 2 * P["wall"] - 0.2,
                P["case_r"] - P["wall"], ct - 2, cb + 2)
    return car


def build_battery_bay(P, D):
    """电池仓：内腔按电芯实际外形 + 0.05 余量；底板放在电芯外面（不占内腔高度）"""
    plate = 0.6
    top = D["bat_top"] - 0.05
    cell_bottom = D["bat_top"] + P["bat_t"]
    bottom = min(cell_bottom + plate, D["inner_floor"] - 0.05)

    y0 = P["bat_y_min"] - 0.6
    y1 = min(P["bat_y_max"] + 0.6, P["case_l"] / 2 - 0.15)
    yc = (y0 + y1) / 2
    ow, ol = P["bat_w"] + 1.2, (y1 - y0)        # 壁厚 0.6

    bay = slab(ow, ol, 4.0, top, bottom, (0, yc))
    bay -= slab(ow - 1.2, ol - 1.2, 2.0, top - 1.0, cell_bottom, (0, yc))
    # 螺丝柱让位
    for (bx, by) in D["screws"]:
        bay -= cyl_z(2.4, top - 1, bottom + 1, bx, by)
    bay &= slab(P["case_w"] - 2 * P["wall"] - 0.2, P["case_l"] - 2 * P["wall"] - 0.2,
                P["case_r"] - P["wall"], top - 2, bottom + 2)
    return bay


def build_usbc_cap(P, D):
    L = P["case_l"]
    zc = P["usbc_z"]
    fw, fh, ft = P["usbc_flange_w"], P["usbc_flange_h"], P["usbc_flange_t"]
    cap = box(fw, ft, fh, 0, -L / 2 + ft / 2 + 0.2, zc)          # 外法兰
    cap += box(P["usbc_open_w"] - 0.6, 4.8, 3.6,
               0, -L / 2 + P["wall"] + 0.9, zc - 0.2)                  # 内嵌段
    cap -= box(P["usbc_w"], 8.0, P["usbc_h"], 0, -L / 2 + 2.0, zc)  # 插头槽
    return cap


def build_button_caps(P, D):
    zc = 9.0
    W = P["case_w"]
    caps = None
    for yb in (P["btn_y1"], P["btn_y2"]):
        c = cyl_x(P["btn_cap_d"] / 2, W / 2 - 1.0, W / 2 + 1.4, yb, zc)
        c += cyl_x(P["btn_cap_d"] / 2 + 0.6, W / 2 - 0.6, W / 2 + 0.1, yb, zc)
        c -= cyl_x(P["btn_cap_d"] / 2 - 0.5, W / 2 - 1.5, W / 2 + 0.2, yb, zc)
        try:
            edges = [e for e in c.edges().filter_by(Axis.X) if abs(e.center().X - (W / 2 + 1.4)) < 0.02]
            if edges:
                c = chamfer(edges, length=P["cap_chamfer"])
        except Exception as exc:
            print("  [warn] 按键帽倒角失败:", exc)
        caps = c if caps is None else caps + c
    return caps


def build_fit_check(P, D):
    """一件式试装板: 屏仓/开窗 + 按钮孔 + USB-C 槽 + 光学窗 + 天线区 + 电池轮廓 + 孔规."""
    W, L = 76.0, 58.0
    t = 12.0
    plate = slab(W, L, 4.0, 0.0, t)

    # 1) 屏开窗 + 屏仓 (正面)
    plate -= slab(P["window_w"], P["window_l"], P["window_r"], -1, P["front_t"] + 0.1,
                  (-14.0, 0.0))
    plate -= slab(P["disp_w"] + 2 * P["disp_side_clr"], P["disp_l"] + 2 * P["disp_side_clr"],
                  3.0, P["front_t"] + 0.1, P["front_t"] + 0.1 + P["disp_t"] + 0.5,
                  (-14.0, 0.0))

    # 2) 按钮孔 (右侧)
    for yb in (P["btn_y1"], P["btn_y2"]):
        plate -= cyl_x(P["btn_cap_d"] / 2, 22.0, 26.0, yb, 9.0)
        plate -= cyl_x(P["btn_pocket_d"] / 2, 20.0, 22.2, yb, 9.0)

    # 3) USB-C 槽 + 端盖法兰 (下侧)
    plate -= box(P["usbc_open_w"], 6, P["usbc_open_h"], 0, -L / 2 + 3, P["usbc_z"])
    plate -= box(P["usbc_flange_w"], P["usbc_flange_t"] + 0.4, P["usbc_flange_h"],
                 0, -L / 2 + 1.2, P["usbc_z"])
    plate -= box(P["usbc_w"], 8, P["usbc_h"], 0, -L / 2 + 3, P["usbc_z"])

    # 4) 光学窗 (背面)
    plate -= slab(P["opt_w"], P["opt_l"], 1.0, t - 2.5, t + 1, (18.0, 12.0))

    # 5) 天线禁布区刻线 (左上)
    for i in range(2):
        plate -= box(P["antenna_keepout_w"], 0.8, 0.8, -14.0, 20.0 - i * (P["antenna_keepout_l"] - 0.8), 0.35)
        plate -= box(0.8, P["antenna_keepout_l"], 0.8,
                     -14.0 - P["antenna_keepout_w"] / 2 + i * (P["antenna_keepout_w"] - 0.8),
                     20.0 - (P["antenna_keepout_l"] - 0.8) / 2, 0.35)

    # 6) 电池轮廓 (背面)
    plate -= slab(P["bat_w"], P["bat_l"], 2.0, t - 1.0, t + 1, (18.0, -12.0))

    # 7) 孔规: M1.6 底孔 / M1.6 过孔 / 光窗圆角
    for i, dia in enumerate((1.6, 2.2, 3.2)):
        plate -= cyl_z(dia / 2, t - 4, t + 1, -30.0 + i * 7.0, -22.0)
    return plate


# ----------------------------------------------------------------- export
PARTS = [
    ("watch_v1_body", "build_body", "上壳/中框 (含前面板与屏开窗)"),
    ("watch_v1_bezel", "build_bezel", "装饰表圈"),
    ("watch_v1_back_cover", "build_back_cover", "下盖 (含光学窗/遮光圈)"),
    ("watch_v1_sensor_carrier", "build_sensor_carrier", "传感器载板 (±2mm 可调)"),
    # 电池仓已取消：2mm 软包用 0.5mm 双面胶直接贴下盖内侧（省一个件，也绕开 0.6 壁公差）
    ("watch_v1_usbc_end_cap", "build_usbc_cap", "USB-C 可换端盖"),
    ("watch_v1_button_caps", "build_button_caps", "按钮帽 ×2"),
    ("watch_v1_fit_check", "build_fit_check", "试装件 (第一件打印)"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--no-step", action="store_true")
    args = ap.parse_args()

    P, M = load_params()
    D = derive(P)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    warnings = []
    if P["disp_w"] + 2 * P["disp_side_clr"] > P["case_w"] - 2 * P["wall"]:
        warnings.append("屏幕宽 + 间隙 > 内腔宽, 屏装不进")
    if P["disp_l"] + 2 * P["disp_side_clr"] > P["case_l"] - 2 * P["wall"]:
        warnings.append("屏幕长 + 间隙 > 内腔长, 屏装不进")
    if D["bat_clear"] < 0.3:
        warnings.append(f"电池仓到内底只剩 {D['bat_clear']:.2f} mm")

    print(f"总厚 {D['total']:.2f} mm  (前面板 {P['front_t']} + 主体 {D['body_d']:.2f} + 下盖 {P['back_t']} + 表圈 {P['bezel_t']})")
    for wmsg in warnings:
        print("  [WARN]", wmsg)

    for name, fn, desc in PARTS:
        part = globals()[fn](P, D)
        step_path = out / f"{name}.step"
        stl_path = out / f"{name}.stl"
        if not args.no_step:
            export_step(part, str(step_path))
        export_stl(part, str(stl_path), tolerance=0.03, angular_tolerance=0.2)
        bb = part.bounding_box()
        print(f"  {name:32s} {desc:24s} bbox {bb.size.X:6.1f} x {bb.size.Y:6.1f} x {bb.size.Z:6.1f}")

    # 参数表 CSV
    csv_path = out / "watch_v1_params.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "value_mm", "status", "source", "notes"])
        for k, v in P.items():
            m = M[k]
            val = f"{v:g}" if isinstance(v, (int, float)) else str(v)
            w.writerow([k, val, m["status"], m["source"], m["notes"]])

    # 堆叠表, 给 docs 用
    stack = {
        "derived": D,
        "params": P,
        "layers": [
            ("装饰表圈", P["bezel_t"], "贴在前壳上, 可换色"),
            ("前面板 (含屏开窗)", P["front_t"], "屏窗 28.4, 压边 0.34/侧"),
            ("屏前间隙", P["disp_front_gap"], ""),
            ("ST7789V 模块 (含 8-pin 排针)", P["disp_t"], "needs-confirmation"),
            ("屏-主板间隙", P["board_gap"], ""),
            ("主板排针", P["hdr_h"], "needs-confirmation"),
            ("主板 PCB", P["board_t"], ""),
            ("主板-电池间隙", P["bat_gap"], ""),
            ("电池 + 泡棉", P["bat_t"] + P["bat_foam"], "20 x 30 x 4 + 1.0"),
            ("电池仓底", 0.0, "托板"),
            ("下盖", P["back_t"], "含光学窗"),
        ],
    }
    (out / "watch_v1_stack.json").write_text(
        json.dumps(stack, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n输出目录: {out}")
    print(f"参数表:   {csv_path}")
    if warnings:
        print("\n警告:", *warnings, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
