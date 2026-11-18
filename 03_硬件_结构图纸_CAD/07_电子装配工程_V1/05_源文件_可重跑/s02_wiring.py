"""Sheet 02 · 软导线连接原理图（点对点，含网络标签与线号）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheet import Sheet, INK, BLUE, GREEN, RED, PURPLE, ORANGE, TEAL, GREY, LIGHT
from nets import NETS, WIRES

s = Sheet("软导线连接原理图 · 点对点 · 30AWG", "H3-E-02", 594, 420)
s.frame("2026-11-04 · 引脚来源：固件 overlay + H3-05 实机接线记录 + 官方 GPIO 图")

NETCOLOR = {
    "3V3": BLUE, "GND": GREEN, "VBAT+": RED, "VBAT−": INK,
    "LCD_SCK": "#1565C0", "LCD_MOSI": "#1B8A2F", "LCD_CS": "#E65100",
    "LCD_DC": "#6A1B9A", "LCD_RES": "#5D4037", "LCD_BL": RED,
    "I2C_SDA": "#F9A825", "I2C_SCL": "#8E24AA",
    "PPG_INT": GREY, "IMU_INT": GREY, "IMU_AD0": INK,
    "KEY_A": TEAL, "KEY_B": TEAL,
}

# ============================================================ MCU 主体
MX, MY, MW, MH = 150, 270, 56, 104
s.rect(MX, MY, MW, MH, INK, 0.9, "#FAFAFA")
s.text(MX + 4, MY + MH - 9, "U1 主控", 4.4, INK, weight="bold")
s.text(MX + 4, MY + MH - 16, "ProMicro nRF52840", 2.9)
s.text(MX + 4, MY + MH - 22, "33.00 × 17.78 × 1.2 mm", 2.5, GREY)
s.text(MX + 4, MY + MH - 28, "长边 12P @2.54 / 短边 7P @2.54", 2.3, GREY)
s.text(MX + 4, MY + MH - 36, "P0.13 = 3V3 使能，固件开机拉高", 2.3, RED)

# 左侧排针（自上而下，与实物丝印一致）
left_pins = [
    ("D4", "P0.22", "I2C_SDA"), ("D5", "P0.24", "I2C_SCL"),
    ("D6", "P1.00", "LCD_DC"),  ("D7", "P0.11", "LCD_RES"),
    ("D8", "P1.04", "KEY_A"),   ("D9", "P1.06", "KEY_B"),
]
y0 = MY + MH - 52
for i, (silk, gpio, net) in enumerate(left_pins):
    y = y0 - i * 10
    s.rect(MX - 6, y - 2.2, 6, 4.4, INK, 0.5, "#FFF3E0")
    s.text(MX - 3, y, silk, 2.2, INK, anchor="c")
    s.text(MX + 2.5, y + 1.6, gpio, 2.2, GREY)
    s.text(MX + 2.5, y - 1.6, net, 2.3, NETCOLOR.get(net, INK), weight="bold")
    s.line([(MX - 6, y), (MX - 24, y)], NETCOLOR.get(net, INK), 0.6)
    s.text(MX - 25, y + 2.2, net, 2.3, NETCOLOR.get(net, INK), anchor="r", weight="bold")

# 右侧排针
right_pins = [
    ("3V3", "3.3V 输出", "3V3"), ("GND", "地", "GND"),
    ("P0.31", "D21", None), ("P0.29", "D20", None),
    ("P1.15", "D18", None), ("P1.13", "D15", None),
    ("P0.09", "D10", None), ("P0.10", "D16", None),
]
for i, (a, b, net) in enumerate(right_pins):
    y = y0 - i * 10
    s.rect(MX + MW, y - 2.2, 6, 4.4, INK, 0.5, "#E8F5E9" if net else "#EEEEEE")
    s.text(MX + MW + 3, y, a if net else a, 2.0, INK, anchor="c")
    if net:
        s.line([(MX + MW + 6, y), (MX + MW + 30, y)], NETCOLOR.get(net, INK), 0.7)
        s.text(MX + MW + 31, y, net, 2.5, NETCOLOR.get(net, INK), weight="bold")
    else:
        s.text(MX + MW + 8, y, "未用（保留）", 2.1, GREY)


# 底部 SPI 焊盘（MCU 下方独立标注）
s.text(MX + 2, MY - 8, "底部 SPI 焊盘（丝印字母）", 2.3, ORANGE, weight="bold")
spi = [("SCK", "P1.01", "LCD_SCK"), ("MOSI", "P1.02", "LCD_MOSI"), ("CS", "P1.07", "LCD_CS")]
for i, (fn, gpio, net) in enumerate(spi):
    x = MX + 3 + i * 18
    s.rect(x, MY - 20, 14, 9, ORANGE, 0.5, "#FFF3E0")
    s.text(x + 7, MY - 13.5, fn, 2.1, ORANGE, anchor="c")
    s.text(x + 7, MY - 17.5, gpio, 1.9, INK, anchor="c")
    s.text(x + 7, MY - 24, net, 2.1, NETCOLOR[net], anchor="c", weight="bold")

# 电池焊盘
s.text(MX + 4, MY - 34, "背面焊盘", 2.3, RED, weight="bold")
s.line([(MX + 6, MY - 38), (MX + 6, MY - 44)], RED, 0.7)
s.text(MX + 6, MY - 46.5, "VBAT+", 2.2, RED, anchor="c")
s.line([(MX + 20, MY - 38), (MX + 20, MY - 44)], INK, 0.7)
s.text(MX + 20, MY - 46.5, "VBAT−", 2.2, INK, anchor="c")

# ============================================================ 连接器（右侧）
DX, DW = 330, 88
def connector(x, y, w, title, pins, accent, note=""):
    h = 14 + len(pins) * 9
    s.rect(x, y - h, w, h, accent, 0.8, "#FFFFFF")
    s.text(x + 4, y - 7.5, title, 3.7, accent, weight="bold")
    if note:
        s.text(x + 4, y - 13.5, note, 2.1, GREY)
    for i, (pin, net) in enumerate(pins):
        yy = y - 21 - i * 9
        s.text(x + 4, yy, pin, 2.2, INK)
        s.text(x + w - 5 - 14, yy, net, 2.3, NETCOLOR.get(net, INK), anchor="r", weight="bold")
        s.line([(x + w - 13, yy), (x + w, yy)], NETCOLOR.get(net, INK), 0.6)
    return y - h

lcd = [("VCC", "3V3"), ("GND", "GND"), ("SCL", "LCD_SCK"), ("SDA", "LCD_MOSI"),
       ("RES", "LCD_RES"), ("DC", "LCD_DC"), ("CS", "LCD_CS"), ("BL", "LCD_BL")]
connector(DX, 386, DW, "H1 ST7789V 1.54\"", lcd, ORANGE, "8P 2.54 · 240×240 IPS · VCC 仅 3.3V")

mx = [("VIN", "3V3"), ("GND", "GND"), ("SCL", "I2C_SCL"), ("SDA", "I2C_SDA"), ("INT", "PPG_INT")]
connector(DX, 306, DW, "H2 MAX30102", mx, PURPLE, "5P 2.54 · I²C 0x57 · 3.3V 兼容版")

mp = [("VCC", "3V3"), ("GND", "GND"), ("SCL", "I2C_SCL"), ("SDA", "I2C_SDA"),
      ("AD0", "IMU_AD0"), ("INT", "IMU_INT")]
connector(DX, 244, DW, "H3 MPU6050 GY-521", mp, PURPLE, "6P 2.54 · I²C 0x68 · AD0 接地")

# 按键
def button(x, y, name, gpio, net):
    s.rect(x, y, 66, 26, TEAL, 0.7, "#F1F8F7")
    s.text(x + 3, y + 19, name, 3.2, TEAL, weight="bold")
    s.text(x + 3, y + 12, f"{gpio} · 6×6 轻触", 2.2, INK)
    s.text(x + 3, y + 5, f"{net} → 脚1 / GND → 脚2", 2.2, TEAL)
    s.line([(x + 66, y + 20), (x + 78, y + 20)], NETCOLOR[net], 0.6)
    s.text(x + 80, y + 20, net, 2.3, NETCOLOR[net], weight="bold")
    s.line([(x + 66, y + 8), (x + 78, y + 8)], GREEN, 0.6)
    s.text(x + 80, y + 8, "GND", 2.3, GREEN, weight="bold")

button(DX + 10, 150, "SW1 按键 A", "P1.04 / D8", "KEY_A")
button(DX + 10, 120, "SW2 按键 B", "P1.06 / D9", "KEY_B")

# ============================================================ 左下：规则
s.rect(18, 14, 230, 58, GREY, 0.5, "#FFFFFF")
s.text(22, 64, "接线规则（必须遵守）", 3.4, INK, weight="bold")
rules = [
    "1. 同名网络标签 = 同一根线；按标签接，不按位置猜。",
    "2. 先接电源地，确认 3V3 正常后再接信号线。",
    "3. 每根线两端套热缩管，焊点不得裸露。",
    "4. 30AWG 仅用于信号；电池线用 26AWG。",
    "5. 线束沿内壁走，禁止压电池或屏排线。",
    "6. 装机前逐根通断测量，记录到线束表。",
    "7. 焊前断电，拔电池后再动烙铁。",
]
for i, r in enumerate(rules):
    s.text(22, 56 - i * 5.4, r, 1.8)

# ============================================================ 中下：线号速查
# 线号/长度完整表见 02_表格/线束表.csv（图纸只标网络名，避免重复信息）
s.rect(340, 62, 236, 30, GREY, 0.5, "#FFFFFF")
s.text(344, 86, "线号与长度：见 02_表格/线束表.csv（W01–W23，共 1370 mm）", 2.3, INK, weight="bold")
s.text(344, 78, "本图只标网络名；同一网络 = 同一根线，按网络名对接。", 2.1, GREY)
s.text(344, 70, "焊前用万用表逐根核对，不合格不装机。", 2.1, GREY)

s.save("02_软导线连接原理图.dxf", "02_软导线连接原理图.png")
print("sheet 02 done")
