"""从 nets.py 生成 CSV + XLSX（引脚分配、网络表、线束表、装配步骤、检查清单）。"""
import os, csv, math, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nets import NETS, WIRES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "02_表格")

# 1) 引脚分配表
PINS = [
 ("U1","主板","3V3","3.3V 输出（受 P0.13 控制）","输出","3V3 母线","—","V1 已验证（H3-05 实机）"),
 ("U1","主板","GND","地","—","GND 母线","—","已验证"),
 ("U1","主板","P0.22 / D4","GPIO / I2C1 SDA","复用","H2/H3 SDA","LCD? 否","已验证（0x68/0x57 扫描）"),
 ("U1","主板","P0.24 / D5","GPIO / I2C1 SCL","复用","H2/H3 SCL","—","已验证"),
 ("U1","主板","P1.00 / D6","GPIO","输出","H1 DC","—","固件 overlay"),
 ("U1","主板","P0.11 / D7","GPIO","输出","H1 RES","—","固件 overlay"),
 ("U1","主板","P1.04 / D8","GPIO 输入（内部上拉）","输入","SW1 KEY_A","—","固件 overlay"),
 ("U1","主板","P1.06 / D9","GPIO 输入（内部上拉）","输入","SW2 KEY_B","—","固件 overlay"),
 ("U1","主板","P1.01（底焊盘）","SPI2 SCK","复用","H1 SCL","—","固件 pinctrl"),
 ("U1","主板","P1.02（底焊盘）","SPI2 MOSI","复用","H1 SDA","—","固件 pinctrl"),
 ("U1","主板","P1.07（底焊盘）","GPIO / SPI CS","输出","H1 CS","—","固件 cs-gpios"),
 ("U1","主板","P0.13","3V3/VCC 输出使能","输出","内部","不可引出","固件 hog high"),
 ("U1","主板","B+ 焊盘","电池正极","电源","BT1 正极","—","板载充电"),
 ("U1","主板","B− 焊盘","电池负极","电源","BT1 负极","—","板载充电"),
 ("U1","主板","P0.31/P0.29/P1.15/P1.13/P0.10/P0.09","GPIO 保留","—","未接","保留","不占用"),
 ("H1","ST7789V","VCC","3.3V","电源","3V3","—","模块标称 3.3V"),
 ("H1","ST7789V","GND","地","电源","GND","—","—"),
 ("H1","ST7789V","SCL","SPI SCK","输入","U1 P1.01","—","—"),
 ("H1","ST7789V","SDA","SPI MOSI","输入","U1 P1.02","—","屏无 MISO"),
 ("H1","ST7789V","RES","复位（低有效）","输入","U1 P0.11","—","—"),
 ("H1","ST7789V","DC","数据/命令","输入","U1 P1.00","—","—"),
 ("H1","ST7789V","CS","片选（低有效）","输入","U1 P1.07","—","—"),
 ("H1","ST7789V","BL","背光","电源","3V3","—","模块带限流"),
 ("H2","MAX30102","VIN","3.3V","电源","3V3","—","需 3.3V 兼容版"),
 ("H2","MAX30102","GND","地","电源","GND","—","—"),
 ("H2","MAX30102","SCL","I2C SCL","双向","I2C_SCL","—","0x57"),
 ("H2","MAX30102","SDA","I2C SDA","双向","I2C_SDA","—","0x57"),
 ("H2","MAX30102","INT","中断","输出","未接","NC","固件未用"),
 ("H3","MPU6050","VCC","3.3V","电源","3V3","—","GY-521 带 LDO"),
 ("H3","MPU6050","GND","地","电源","GND","—","—"),
 ("H3","MPU6050","SCL","I2C SCL","双向","I2C_SCL","—","0x68"),
 ("H3","MPU6050","SDA","I2C SDA","双向","I2C_SDA","—","0x68"),
 ("H3","MPU6050","AD0","地址选择","输入","GND","—","接地=0x68"),
 ("H3","MPU6050","INT","中断","输出","未接","NC","固件未用"),
 ("SW1","6×6 轻触","脚1/脚2","KEY_A","开关","P1.04 / GND","—","4 脚按键用对角"),
 ("SW2","6×6 轻触","脚1/脚2","KEY_B","开关","P1.06 / GND","—","4 脚按键用对角"),
 ("BT1","LiPo 250mAh","正极","VBAT+","电源","U1 B+","—","带保护板"),
 ("BT1","LiPo 250mAh","负极","VBAT−","电源","U1 B−","—","禁止反接"),
]
with open(os.path.join(OUT, "引脚分配表.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["器件","型号/位号","引脚(丝印)","功能","方向","连接目标","备注","证据/状态"]); w.writerows(PINS)

# 2) 网络表
with open(os.path.join(OUT, "网络表.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["网络","源器件","源引脚","目标器件","目标引脚","线色","类别","备注"]); w.writerows(NETS)

# 3) 线束表（长度公式 L=ceil5(d*k+loop)）
def ceil5(v): return int(math.ceil(v / 5.0) * 5)
rows = []
tot = 0
for wid, net, a, b, d, k, loop, awg, color, path in WIRES:
    L = ceil5(d * k + loop)
    tot += L
    rows.append([wid, net, a, b, d, k, loop, L, awg, color, path])
with open(os.path.join(OUT, "线束表.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["线号","网络","起点","终点","直线距离mm","走线系数","服务环mm","下料长度mm","线规","颜色","走线路径"])
    w.writerows(rows)
    w.writerow([])
    w.writerow(["合计","","","", "", "", "", tot, "", "", f"{len(rows)} 根；含 10% 备料 = {ceil5(tot*1.1)} mm"])

# 4) XLSX
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    wb = Workbook()
    hdr_fill = PatternFill("solid", fgColor="1F4E79")
    hdr_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    def sheet(name, header, data, widths):
        ws = wb.create_sheet(name)
        ws.append(header)
        for c in ws[1]:
            c.fill = hdr_fill; c.font = hdr_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        for r in data:
            ws.append(r)
        for col, wd in zip("ABCDEFGHIJK", widths):
            ws.column_dimensions[col].width = wd
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.border = border
                c.alignment = Alignment(vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"
    wb.remove(wb.active)
    sheet("引脚分配", ["器件","型号/位号","引脚(丝印)","功能","方向","连接目标","备注","证据/状态"],
          PINS, [8,16,26,26,8,20,16,26])
    sheet("网络表", ["网络","源器件","源引脚","目标器件","目标引脚","线色","类别","备注"],
          NETS, [12,14,18,16,18,8,8,34])
    sheet("线束表", ["线号","网络","起点","终点","直线距离mm","走线系数","服务环mm","下料长度mm","线规","颜色","走线路径"],
          rows + [["合计","","","","","","",tot,"","",f"{len(rows)} 根；含10%备料={ceil5(tot*1.1)}mm"]],
          [7,12,20,18,11,9,10,11,8,7,40])
    wb.save(os.path.join(OUT, "SenseMind_H3-05_电子装配_表格.xlsx"))
    print("xlsx ok")
except ImportError as e:
    print("no openpyxl:", e)

print("wires:", len(rows), "total mm:", tot)
