"""SenseMind 电子装配图纸绘制库（DXF + PNG 双输出）。

坐标系：1:1 毫米，Y 向上。每个 sheet 是一个 A2 横向 (594 x 420) 的图框。
所有图元先记录，再分别用 ezdxf 与 matplotlib 输出，保证 DXF 与 PNG 一致。
"""
from __future__ import annotations

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import Rectangle, Circle, Polygon, FancyArrowPatch
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

import os
CJK_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "SenseMindCJK.ttf")
CJK_NAME = "SenseMind CJK"
fm.fontManager.addfont(CJK_FONT)
_FP = fm.FontProperties(fname=CJK_FONT)
try:
    fm.fontManager.addfont("/Library/Fonts/Arial Unicode.ttf")
except Exception:
    pass

INK = "#111111"
BLUE = "#1565C0"      # 3V3
GREEN = "#1B8A2F"     # GND
RED = "#C62828"       # 电池 / 电源
PURPLE = "#6A1B9A"    # I2C
ORANGE = "#E65100"    # SPI
TEAL = "#00695C"      # 按键
GREY = "#757575"
LIGHT = "#F2F2F2"

NET_COLOR = {
    "3V3": BLUE, "GND": GREEN, "VBAT": RED, "VUSB": RED,
    "I2C": PURPLE, "SPI": ORANGE, "KEY": TEAL, "SIG": INK,
}


class Sheet:
    def __init__(self, title: str, number: str, w: float = 594, h: float = 420):
        self.w, self.h = w, h
        self.items = []          # (kind, payload, layer, color, width)
        self.title = title
        self.number = number

    # ---------------- primitives ----------------
    def rect(self, x, y, w, h, color=INK, width=0.5, fill=None, layer="0"):
        self.items.append(("rect", (x, y, w, h, fill), layer, color, width))

    def line(self, pts, color=INK, width=0.35, dash=None, layer="0"):
        self.items.append(("line", (list(pts), dash), layer, color, width))

    def circle(self, x, y, r, color=INK, width=0.4, fill=None, layer="0"):
        self.items.append(("circle", (x, y, r, fill), layer, color, width))

    def poly(self, pts, color=INK, width=0.4, fill=None, closed=True, layer="0"):
        self.items.append(("poly", (list(pts), closed, fill), layer, color, width))

    def text(self, x, y, s, size=3.2, color=INK, anchor="l", weight="normal",
             rotation=0, layer="TEXT"):
        self.items.append(("text", (x, y, s, size, anchor, weight, rotation), layer, color, 0))

    def arrow(self, x1, y1, x2, y2, color=INK, width=0.4, style="-|>", layer="0"):
        self.items.append(("arrow", (x1, y1, x2, y2, style), layer, color, width))

    # ---------------- page furniture ----------------
    def frame(self, sub: str = ""):
        m = 10
        self.rect(m, m, self.w - 2 * m, self.h - 2 * m, INK, 0.8)
        self.rect(m + 2, m + 2, self.w - 2 * m - 4, self.h - 2 * m - 4, GREY, 0.25)
        # 标题栏（右下角，独立于绘图区）
        bw, bh = 190, 40
        bx, by = self.w - m - 2 - bw, m + 2
        self.rect(bx, by, bw, bh, INK, 0.7, "#FFFFFF")
        self.line([(bx, by + 12), (bx + bw, by + 12)], GREY, 0.25)
        self.line([(bx, by + 26), (bx + bw, by + 26)], GREY, 0.25)
        self.line([(bx + 108, by), (bx + 108, by + 26)], GREY, 0.25)
        self.text(bx + 4, by + 33, "SenseMind H3-05 电子装配 V1", 4.6, INK, weight="bold")
        self.text(bx + 4, by + 19, self.title, 3.4)
        self.text(bx + 4, by + 5, "研究原型 · 非医疗器械 · mm", 2.6, GREY)
        self.text(bx + 112, by + 19, f"图号 {self.number}", 3.0)
        self.text(bx + 112, by + 5, sub or "2026-11-04", 2.4, GREY)
        # 图名与副标题（左上角）
        self.text(m + 6, self.h - m - 9, self.title, 6.4, INK, weight="bold")
        if sub:
            self.text(m + 6, self.h - m - 15.5, sub, 3.0, GREY)

    # ---------------- export ----------------
    def _dxf(self, path):
        doc = ezdxf.new("R2010", setup=True)
        if "DASHED" not in doc.linetypes:
            doc.linetypes.add("DASHED", pattern=[0.6, 0.3, -0.2], description="Dashed __ __ __")
        doc.styles.add("CJK", font=CJK_FONT)
        msp = doc.modelspace()
        for kind, payload, layer, color, width in self.items:
            if not doc.layers.has_entry(layer):
                doc.layers.add(layer, color=7)
            if kind == "rect":
                x, y, w, h, fill = payload
                hatch = None
                if fill:
                    hatch = msp.add_hatch(color=8)
                    hatch.paths.add_polyline_path(
                        [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], is_closed=True)
                    hatch.rgb = self._rgb(fill)
                msp.add_lwpolyline(
                    [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                    close=True, dxfattribs={"layer": layer, "lineweight": int(width * 13)})
            elif kind == "line":
                pts, dash = payload
                att = {"layer": layer, "lineweight": int(width * 13)}
                if dash:
                    att["linetype"] = "DASHED"
                msp.add_lwpolyline(pts, dxfattribs=att)
            elif kind == "circle":
                x, y, r, fill = payload
                msp.add_circle((x, y), r, dxfattribs={"layer": layer, "lineweight": int(width * 13)})
            elif kind == "poly":
                pts, closed, fill = payload
                if fill:
                    hatch = msp.add_hatch(color=8)
                    hatch.paths.add_polyline_path(pts, is_closed=True)
                    hatch.rgb = self._rgb(fill)
                msp.add_lwpolyline(pts, close=closed,
                                   dxfattribs={"layer": layer, "lineweight": int(width * 13)})
            elif kind == "text":
                x, y, s, size, anchor, weight, rotation = payload
                att = {"layer": layer, "style": "CJK", "height": size, "rotation": rotation}
                t = msp.add_text(s, dxfattribs=att)
                from ezdxf.enums import TextEntityAlignment
                align = {"l": TextEntityAlignment.LEFT,
                         "c": TextEntityAlignment.CENTER,
                         "r": TextEntityAlignment.RIGHT}[anchor]
                t.set_placement((x, y), align=align)
        doc.saveas(path)
        return doc

    @staticmethod
    def _rgb(hexcolor):
        h = hexcolor.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def save(self, dxf_path, png_path, dpi=220):
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(base)
        dxf_path = os.path.join(root, "03_图纸_可编辑DXF", os.path.basename(dxf_path))
        png_path = os.path.join(root, "04_图纸_预览PNG", os.path.basename(png_path))
        doc = self._dxf(dxf_path)
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [CJK_NAME, "Arial Unicode MS", "DejaVu Sans"]
        plt.style.use("default")
        plt.rcParams.update({
            "figure.facecolor": "white", "axes.facecolor": "white",
            "savefig.facecolor": "white", "savefig.transparent": False,
        })
        fig = plt.figure(figsize=(self.w / 25.4, self.h / 25.4), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor("white")
        ax.patch.set_facecolor("white")
        ax.patch.set_alpha(1.0)
        fig.patch.set_facecolor("white")
        ax.add_patch(Rectangle((0, 0), self.w, self.h, facecolor="white",
                               edgecolor="none", zorder=-100))
        self._mpl(ax)
        ax.set_xlim(0, self.w)
        ax.set_ylim(0, self.h)
        ax.set_aspect("equal")
        ax.axis("off")
        fig.savefig(png_path, dpi=dpi, facecolor="white", transparent=False)
        plt.close(fig)

    def _mpl(self, ax):
        for kind, payload, layer, color, width in self.items:
            lw = max(0.5, width * 1.15)
            if kind == "rect":
                x, y, w, h, fill = payload
                kw = dict(facecolor=fill, edgecolor=color, linewidth=lw, alpha=1.0) if fill \
                     else dict(fill=False, edgecolor=color, linewidth=lw, alpha=1.0)
                ax.add_patch(Rectangle((x, y), w, h, **kw))
            elif kind == "line":
                pts, dash = payload
                xs, ys = zip(*pts)
                ax.plot(xs, ys, color=color, linewidth=lw,
                        linestyle=(0, (4, 3)) if dash else "-", solid_capstyle="round")
            elif kind == "circle":
                x, y, r, fill = payload
                kw = dict(facecolor=fill, edgecolor=color, linewidth=lw, alpha=1.0) if fill \
                     else dict(fill=False, edgecolor=color, linewidth=lw, alpha=1.0)
                ax.add_patch(Circle((x, y), r, **kw))
            elif kind == "poly":
                pts, closed, fill = payload
                kw = dict(facecolor=fill, edgecolor=color, linewidth=lw, alpha=1.0) if fill \
                     else dict(fill=False, edgecolor=color, linewidth=lw, alpha=1.0)
                ax.add_patch(Polygon(pts, closed=closed, **kw))
            elif kind == "text":
                x, y, s, size, anchor, weight, rotation = payload
                h = {"l": "left", "c": "center", "r": "right"}[anchor]
                ax.text(x, y, s, fontsize=size * 2.55, color=color,
                        ha=h, va="center", weight=weight, rotation=rotation,
                        rotation_mode="anchor", fontproperties=_FP)
            elif kind == "arrow":
                x1, y1, x2, y2, style = payload
                ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                             mutation_scale=9, color=color, linewidth=lw))
