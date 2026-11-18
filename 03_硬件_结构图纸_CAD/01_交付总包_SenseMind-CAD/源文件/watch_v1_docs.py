#!/usr/bin/env python3
"""SenseMind H3-05 手表 V1 - 出图 (三视图 / 剖面 / 爆炸 / 参数状态).

读取 watch_v1_stack.json + watch_v1_params.json, 输出:
  watch_v1_drawings.pdf   顶视图 + 双区剖面 + 参数状态表
  watch_v1_assembly.pdf   真实几何爆炸轴测 + 打印/螺丝/风险

爆炸图与剖面由 build123d 几何投影得到, 不是手画示意图。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

INK = "#1a1a1a"
DIM = "#c0392b"
ASSUMED = "#d35400"
OK = "#1e8449"
FAINT = "#9a9a9a"

C_BEZEL = "#dfe6e9"
C_PANEL = "#b2bec3"
C_DISP = "#74b9ff"
C_HDR = "#fdcb6e"
C_BOARD = "#55efc4"
C_BAT = "#ffeaa7"
C_CARRIER = "#d6a2e8"
C_SENSOR = "#fab1a0"
C_CAV = "#f7f7f7"


def outdir():
    """优先用 out/ 子目录；没有就当作脚本所在目录（扁平交付目录）"""
    cand = HERE / "out" / "watch_v1_stack.json"
    return HERE / "out" if cand.exists() else HERE


def load():
    stack = json.loads((outdir() / "watch_v1_stack.json").read_text(encoding="utf-8"))
    data = json.loads((HERE / "watch_v1_params.json").read_text(encoding="utf-8"))
    return stack, data["params"], data["meta"]


def page(title, subtitle=""):
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0.04, 0.04, 0.92, 0.86])
    ax.set_aspect("equal")
    ax.axis("off")
    fig.text(0.035, 0.955, title, fontsize=16, weight="bold", color=INK)
    if subtitle:
        fig.text(0.035, 0.924, subtitle, fontsize=9, color="#555")
    return fig, ax


def dim_h(ax, x1, x2, y, label, color=DIM, size=7.5):
    ax.annotate("", xy=(x1, y), xytext=(x2, y),
                arrowprops=dict(arrowstyle="<|-|>", color=color, lw=0.9,
                                shrinkA=0, shrinkB=0, mutation_scale=8))
    ax.text((x1 + x2) / 2, y + 1.4, label, ha="center", va="bottom",
            fontsize=size, color=color)


def dim_v(ax, y1, y2, x, label, color=DIM, size=7.5):
    ax.annotate("", xy=(x, y1), xytext=(x, y2),
                arrowprops=dict(arrowstyle="<|-|>", color=color, lw=0.9,
                                shrinkA=0, shrinkB=0, mutation_scale=8))
    ax.text(x + 1.2, (y1 + y2) / 2, label, rotation=90, ha="left", va="center",
            fontsize=size, color=color)


def note(ax, x, y, s, size=7, color="#555", **kw):
    ax.text(x, y, s, fontsize=size, color=color, **kw)


def rbox(ax, x, y, w, h, r, **kw):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle=f"round,pad=0,rounding_size={r}",
                                fill=False, **kw))


# --------------------------------------------------------------- 顶视图
def sheet_top_view(P, D, stack):
    W, L = P["case_w"], P["case_l"]
    lw, ll = P["lug_w"], P["lug_len"]
    fig, ax = page("SenseMind H3-05 手表 V1 · 顶视图 (从屏幕侧看, XY)",
                   "单位 mm · 橙色 = assumed/待实测 · 本图由 watch_v1_params.json 自动生成, 非最终图纸")

    # 表耳
    for sy in (+1, -1):
        for sx in (+1, -1):
            x = sx * (P["strap_w"] / 2 + lw / 2)
            ax.add_patch(Rectangle((x - lw / 2, sy * L / 2 if sy > 0 else -L / 2 - ll),
                                   lw, ll, fill=False, ec=INK, lw=1.0, ls=(0, (4, 2))))
            ax.add_patch(plt.Circle((x, sy * (L / 2 + ll - 2.0)), P["bar_d"] / 2,
                                    fill=False, ec=INK, lw=0.8))

    rbox(ax, -W / 2, -L / 2, W, L, P["case_r"], ec=INK, lw=1.5)
    rbox(ax, -P["window_w"] / 2, -P["window_l"] / 2, P["window_w"], P["window_l"],
         P["window_r"], ec=OK, lw=1.1)
    ax.add_patch(Rectangle((-P["disp_w"] / 2, -P["disp_l"] / 2), P["disp_w"], P["disp_l"],
                           fill=False, ec=ASSUMED, ls=(0, (2, 2)), lw=0.9))
    ax.add_patch(Rectangle((-P["disp_active"] / 2, -P["disp_active"] / 2),
                           P["disp_active"], P["disp_active"],
                           fill=False, ec=FAINT, ls=(0, (1, 2)), lw=0.9))
    ax.text(0, P["disp_active"] / 2 - 2.2, f"有效区 {P['disp_active']:g}",
            fontsize=7.2, color=FAINT, ha="center", va="top")

    # 按钮
    for i, yb in enumerate((P["btn_y1"], P["btn_y2"])):
        ax.add_patch(plt.Circle((W / 2, yb), P["btn_cap_d"] / 2, fill=False, ec=INK, lw=1.1))
        ax.text(W / 2 + 2.6, yb + (1.0 if i == 0 else -1.0),
                f"{'A' if i == 0 else 'B'} Ø{P['btn_cap_d']:g}",
                fontsize=7.2, va="center")

    # USB-C (6 点)
    ax.add_patch(Rectangle((-P["usbc_w"] / 2, -L / 2), P["usbc_w"], 1.4,
                           fill=False, ec=INK, lw=1.1))
    ax.text(0, -L / 2 - 4.0, f"USB-C {P['usbc_w']:g}×{P['usbc_h']:g}",
            fontsize=7.2, ha="center")

    # 光学窗
    ax.add_patch(Rectangle((P["max_x"] - P["opt_w"] / 2, P["sensor_y"] - P["opt_l"] / 2),
                           P["opt_w"], P["opt_l"], fill=True, fc="#f3e8ff",
                           ec="#8e44ad", lw=1.1))
    ax.text(P["max_x"], P["sensor_y"], f"光学窗\n{P['opt_w']:g}×{P['opt_l']:g}",
            fontsize=6.8, ha="center", va="center", color="#6c3483")

    # 天线禁布: 12 点侧壁内侧
    ax.add_patch(Rectangle((-P["antenna_keepout_w"] / 2, L / 2 - 3.4),
                           P["antenna_keepout_w"], 3.4,
                           fill=True, fc="#eaf4fd", ec="#2980b9", ls=(0, (3, 2)), lw=1.0))
    ax.text(0, L / 2 - 1.7, "天线禁布 15×10 (侧壁内侧)",
            fontsize=6.4, ha="center", va="center", color="#1f618d")

    # 尺寸
    dim_h(ax, -W / 2, W / 2, -L / 2 - 8.5, f"{W:g}")
    dim_v(ax, -L / 2, L / 2, W / 2 + 8.0, f"{L:g}", color=INK)
    dim_h(ax, -P["window_w"] / 2, P["window_w"] / 2, L / 2 + ll + 3.0, f"开窗 {P['window_w']:g}")
    dim_h(ax, -P["strap_w"] / 2, P["strap_w"] / 2, L / 2 + ll + 8.0, f"表带 {P['strap_w']:g}")

    ax.annotate(f"屏模块外形 {P['disp_w']:g}×{P['disp_l']:g} (measured)",
                xy=(-P["disp_w"] / 2, -P["disp_l"] / 2 + 4),
                xytext=(-W / 2 - 15.0, -L / 2 + 2.0), fontsize=7.2, color=ASSUMED,
                arrowprops=dict(arrowstyle="-", color=ASSUMED, lw=0.6))

    ax.text(-W / 2 - 15.0, L / 2 - 2.0,
            "压边 0.34/侧 ≤ 0.4\n屏仓间隙 0.5/侧\n键距 10 / 键帽 Ø3.4\n表耳 6×5, 生耳 Ø1.6",
            fontsize=7.2, va="top")
    ax.text(-W / 2 - 15.0, L / 2 - 9.5,
            f"外形 R{P['case_r']:g}\n表圈厚 {P['bezel_t']:g}\n表带 {P['strap_w']:g} mm",
            fontsize=7.2, va="top")

    ax.set_xlim(-W / 2 - 17, W / 2 + 14)
    ax.set_ylim(-L / 2 - 14, L / 2 + ll + 12)
    return fig


# ---------------------------------------------------------------- 剖面
def _stack_rows(P, D, zone):
    rows = [
        ("装饰表圈", P["bezel_t"], C_BEZEL),
        ("前面板", P["front_t"], C_PANEL),
        ("屏前间隙", P["disp_front_gap"], "white"),
        ("ST7789V 模块", P["disp_t"], C_DISP),
        ("屏-板间隙", P["board_gap"], "white"),
        ("排针", P["hdr_h"], C_HDR),
        ("主板 PCB", P["board_t"], C_BOARD),
    ]
    if zone == "bat":
        rows += [("板-电池间隙", P["bat_gap"], "white"),
                 ("电池 + 泡棉", P["bat_t"] + P["bat_foam"], C_BAT)]
    else:
        rows += [("板-载板间隙", P["carrier_gap"], "white"),
                 ("传感器载板", P["carrier_t"], C_CARRIER),
                 ("MAX30102 / MPU6050", max(P["max_t"], P["mpu_t"]), C_SENSOR)]
    used = sum(t for _, t, _ in rows)
    floor = P["bezel_t"] + D["inner_floor"]
    rows += [(f"空腔 / 下盖内面", max(floor - used, 0.0), C_CAV),
             ("下盖", P["back_t"], C_PANEL)]
    return rows


def _draw_stack(ax, P, D, title, zone, x0):
    rows = _stack_rows(P, D, zone)
    w = P["case_w"] - 2 * P["wall"]
    z = 0.0
    ax.text(x0, 5.2, title, ha="center", va="center", fontsize=10, weight="bold")
    for name, t, color in rows:
        if t <= 0.001:
            continue
        z -= t
        ax.add_patch(Rectangle((x0 - w / 2, z), w, t, facecolor=color,
                               edgecolor=INK, lw=0.7))
        if t >= 0.28:
            ax.text(x0 + w / 2 + 1.6, z + t / 2, f"{t:.2f}", ha="left", va="center",
                    fontsize=6.8, color=DIM)
    return z


def _legend(fig, P):
    items = [
        ("表圈", C_BEZEL), ("前/下盖", C_PANEL), ("间隙", "white"),
        ("屏模块", C_DISP), ("排针", C_HDR), ("主板", C_BOARD),
        ("电池(12点)", C_BAT), ("载板(6点)", C_CARRIER), ("传感器(6点)", C_SENSOR),
    ]
    x = 0.05
    for name, color in items:
        fig.patches.append(Rectangle((x, 0.245), 0.011, 0.015, transform=fig.transFigure,
                                     facecolor=color, edgecolor=INK, lw=0.6))
        fig.text(x + 0.015, 0.2455, name, fontsize=7.4, va="bottom")
        x += 0.015 + 0.0092 * len(name) + 0.028


def sheet_section(P, D, stack):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.035, 0.955, "SenseMind H3-05 手表 V1 · 剖面 (12 点区 / 6 点区)",
             fontsize=16, weight="bold")
    fig.text(0.035, 0.924,
             f"总厚 {D['total']:.2f} mm · 两区共用一个内底面 (深 {D['inner_floor']:.2f}) · 右侧数字 = 该层厚度 mm",
             fontsize=9, color="#555")
    ax = fig.add_axes([0.05, 0.30, 0.90, 0.56])
    ax.set_aspect("equal")
    ax.axis("off")
    _draw_stack(ax, P, D, "12 点区: 屏 → 主板 → 电池", "bat", -22.0)
    _draw_stack(ax, P, D, "6 点区: 屏 → 主板 → 传感器载板", "sensor", 22.0)

    dim_v(ax, -(D["total"]), 0, -46.0, f"总厚 {D['total']:.2f}", color=INK)
    ax.set_xlim(-50, 50)
    ax.set_ylim(-D["total"] - 8, 9)

    _legend(fig, P)

    lines = [
        f"最小厚度 = 表圈 {P['bezel_t']} + 前面板 {P['front_t']} + 屏前隙 {P['disp_front_gap']} + 屏 {P['disp_t']} "
        f"+ 隙 {P['board_gap']} + 排针 {P['hdr_h']} + 板 {P['board_t']} + 隙 {P['bat_gap']} "
        f"+ 电池 {P['bat_t']}+泡棉 {P['bat_foam']} + 下盖 {P['back_t']} = {D['total']:.2f} mm",
        f"传感器侧: 载板顶 {D['carrier_top']:.2f} → 模块底 {D['sensor_bot']:.2f} → 内底 {D['inner_floor']:.2f}; "
        f"电池底 {D['bat_bot']:.2f}, 余量 {D['bat_clear']:.2f} mm (由泡棉压缩吸收)",
        "18 mm 目标: 必须去排针/改 FPC 或裸芯片; 当前模块组合最小只能到约 "
        f"{D['total']:.1f} mm, 不得压缩模块/电池",
    ]
    y = 0.20
    for s in lines:
        fig.text(0.05, y, s, fontsize=8.6, color="#222")
        y -= 0.028
    fig.text(0.05, 0.10,
             "屏托边在两侧壁内侧 (X ±12 范围内), 屏背面坐在托边上; 剖面取 X=0 可见托边截面。",
             fontsize=8.2, color="#555")
    fig.text(0.05, 0.072,
             f"V1.3 实测: 屏 {P['disp_w']:g}×{P['disp_l']:g}×{P['disp_t']:g} / 主板 {P['board_w']:g}×{P['board_l']:g}×{P['board_t']:g} / 排针 {P['hdr_h']:g} / 传感器 {P['max_t']:g} / 电池 {P['bat_w']:g}×{P['bat_l']:g}×{P['bat_t']:g}",
             fontsize=8.2, color=ASSUMED)
    return fig


# ------------------------------------------------------------ 参数状态表
def sheet_params_page(P, M):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.035, 0.955, "参数状态表 (measured / assumed / needs-confirmation)",
             fontsize=15, weight="bold")
    fig.text(0.035, 0.925,
             "所有 assumed 不得当成实测; needs-confirmation 必须先用卡尺量, 量完改 watch_v1_params.json 后重跑脚本",
             fontsize=9, color="#555")
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.84])
    ax.axis("off")
    order = {"measured": 0, "needs-confirmation": 1, "assumed": 2}
    keys = sorted(P, key=lambda k: (order.get(M[k]["status"], 9), k))
    per = (len(keys) + 2) // 3
    for i, k in enumerate(keys):
        c, r = divmod(i, per)
        x = 0.01 + c * 0.335
        y = 0.965 - r * 0.0395
        st = M[k]["status"]
        color = {"measured": OK, "needs-confirmation": DIM}.get(st, ASSUMED)
        ax.text(x, y, k, fontsize=6.4, color=INK, family="monospace")
        v = P[k]
        vt = f"{v:g}" if isinstance(v, (int, float)) else str(v)[:14]
        ax.text(x + 0.105, y, vt, fontsize=6.4, color=INK,
                ha="right", family="monospace")
        ax.text(x + 0.115, y, st[:12], fontsize=6.0, color=color)
    fig.text(0.04, 0.035,
             "绿色 = 数据手册/供应商图纸可查; 红色 = 必须实测; 橙色 = 设计假设 (改参数即可重生)",
             fontsize=8, color="#555")
    return fig


# ------------------------------------------------------- 真实几何投影
def _edge_points(e, n=10):
    pts = []
    for i in range(n + 1):
        t = i / n
        try:
            p = e.position_at(t)
        except Exception:
            p = e @ t
        pts.append((p.X, p.Y))
    return pts


def _project(shape, origin=(150, -190, 120)):
    try:
        visible, hidden = shape.project_to_viewport(origin)
    except Exception as exc:
        print("project fail:", exc)
        return []
    return [_edge_points(e) for e in visible]


def _board_schematic(P, D):
    from build123d import Box, Pos
    from watch_v1_cad import cyl_x

    y0 = P["board_y_top"] - P["board_l"]
    yc = y0 + P["board_l"] / 2
    b = Pos(0, yc, -(D["board_top"] + P["board_t"]) / 2) * Box(P["board_w"], P["board_l"], P["board_t"])
    b += Pos(0, yc, -(D["hdr_top"] + D["board_top"]) / 2) * Box(
        P["board_w"] - 4, P["board_l"] - 6, P["hdr_h"])
    b += Pos(0, y0 + 3.0, -(D["board_top"] - 1.6)) * Box(9.0, 6.0, 3.2)
    return b


def sheet_exploded(P, D):
    import watch_v1_cad as cad

    items = [
        ("下盖 back_cover", cad.build_back_cover, -58),
        ("电池仓 battery_bay", cad.build_battery_bay, -34),
        ("传感器载板 sensor_carrier", cad.build_sensor_carrier, -16),
        ("主板 + 排针 (示意)", None, 2),
        ("中框/上壳 body", cad.build_body, 30),
        ("表圈 bezel", cad.build_bezel, 62),
    ]

    fig, ax = page("SenseMind H3-05 手表 V1 · 爆炸轴测 (真实几何投影)",
                   "装配顺序由下往上: 下盖 → 电池仓 → 传感器载板 → 主板 → 中框 → 表圈 · 单位 mm")
    for label, fn, shift in items:
        part = _board_schematic(P, D) if fn is None else fn(P, D)
        segs = _project(part)
        if not segs:
            continue
        xs_all, ys_all = [], []
        for seg in segs:
            xs = [p[0] for p in seg]
            ys = [p[1] + shift for p in seg]
            ax.plot(xs, ys, color=INK, lw=0.45)
            xs_all += xs
            ys_all += ys
        if xs_all:
            ax.text(max(xs_all) + 6, (min(ys_all) + max(ys_all)) / 2, label,
                    fontsize=8, va="center", color="#333")
    ax.autoscale_view()
    ax.margins(0.10)
    return fig


def sheet_print_notes(P, D):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.955, "打印建议 / 螺丝清单 / 风险", fontsize=15, weight="bold")
    blocks = [
        ("第一件必须打: watch_v1_fit_check.stl", DIM, True),
        ("验证: 屏开窗 + 屏仓深度, 按钮孔与内侧让位, USB-C 槽 + 端盖法兰, 光学窗, 天线禁布区, 电池轮廓, Ø1.6/2.2/3.2 孔规", "#333", False),
        ("", "#333", False),
        ("打印参数 (FDM 原型)", INK, True),
        (f"  壁厚 {P['wall']} / 层高 0.16 / 3 周壁 / 3 顶底 / 15% 填充 / 0.4 喷嘴", "#333", False),
        ("  上壳: 前面板朝下贴板, 不用支撑; 屏托边是悬空 shelf, 可桥接 (建议 45° 或加 1 层支撑)", "#333", False),
        ("  下盖: 外表面朝下 (纹理面), 光学窗/遮光圈周围需支撑", "#333", False),
        ("  表圈 / 端盖 / 按钮帽: 平放, 0.12 层高; 树脂 (SLA) 优先, 精度和手感更好", "#333", False),
        ("  装配间隙: FDM 0.3–0.45; 树脂 0.2; 打印前先打 0.1/0.15/0.2/0.25 间隙试片标定收缩", "#333", False),
        ("", "#333", False),
        ("螺丝清单", INK, True),
        ("  4 × M1.6 × 8 (自攻, 或 M1.6 热熔铜螺母 + 机丝): 下盖 → 中框螺丝柱", "#333", False),
        ("  2 × M1.6 × 6: 传感器载板 ±2 mm 可调槽 → 下盖立柱", "#333", False),
        ("  表圈: 0.15 mm 3M 双面胶 或 点胶 (要可拆就用胶带, 不粘死)", "#333", False),
        ("  USB-C 端盖: 摩擦配合 + 硅胶塞, 不粘死 (可换件)", "#333", False),
        ("", "#333", False),
        ("风险 / 待确认", DIM, True),
        ("  1) 屏/主板/电池/传感器均按游标卡尺实测 (2026-11-03); 改尺寸只需改 watch_v1_params.json", "#333", False),
        ("  2) USB-C 在短边、天线在对端 (keepout 15×10) 未验证; 不符则改参数, 端盖是独立件", "#333", False),
        ("  3) USB-C 中心深度 usbc_z 由主板实测决定; 端盖独立, 改它不动整壳", "#333", False),
        ("  4) 30×20×4 电池放 12 点区; 25×30×4.5 会顶到传感器区, 厚度涨到约 25–26", "#333", False),
        ("  5) 光学窗中心 X = -4.56 (内腔宽度限制); 实测光窗位置不同则改 max_x / opt_w", "#333", False),
        ("  6) 光窗到皮肤 0.8; 遮光圈是 0.4 黑色泡棉环, 需实测压缩后不漏光", "#333", False),
        ("  7) 天线区只有塑料, 但电池/排线走位仍需装配后实测 BLE 距离", "#333", False),
        ("", "#333", False),
        ("声明: 非医疗产品; 不声明 IP 防护等级; 未做真机跌落/汗液/生物相容性验证", DIM, True),
    ]
    y = 0.905
    for text, color, bold in blocks:
        fig.text(0.05, y, text, fontsize=9.2, color=color,
                 weight="bold" if bold else "normal")
        y -= 0.0365
    return fig


def main():
    stack, P, M = load()
    D = stack["derived"]
    out = outdir()

    with PdfPages(out / "watch_v1_drawings.pdf") as pdf:
        for fn in (sheet_top_view, sheet_section):
            fig = fn(P, D, stack)
            pdf.savefig(fig)
            plt.close(fig)
        fig = sheet_params_page(P, M)
        pdf.savefig(fig)
        plt.close(fig)

    with PdfPages(out / "watch_v1_assembly.pdf") as pdf:
        for fn in (sheet_exploded, sheet_print_notes):
            fig = fn(P, D)
            pdf.savefig(fig)
            plt.close(fig)

    print("wrote", out / "watch_v1_drawings.pdf")
    print("wrote", out / "watch_v1_assembly.pdf")


if __name__ == "__main__":
    main()
