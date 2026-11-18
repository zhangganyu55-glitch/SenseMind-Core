# SenseMind_Hardware_V1 原理图交付说明

生成时间：2026-10-31 23:52（Asia/Shanghai）
执行者：DeepSeek Harness · 通过 EasyEDA Bridge（127.0.0.1:49620）
工程：`SenseMind_Hardware_V1`（UUID `f765b1f8…`），嘉立创EDA专业版 4.1.78，**半离线模式**

---

## 1. 状态总览

| 页面 | 实际画了什么 | 自检 | 备注 |
|---|---|---|---|
| 01_System_Overview | 双终端框图、供电与通信关系、DNP 与待确认清单 | 0 错误 | 纯图形页 |
| 02_NRF52840_Main | J101（1×12 2.54mm）+ 12 条命名网络 + U101 模块说明块 | 0 错误 | **U101 无库符号**（见第 5 节） |
| 03_MAX30102_PPG | J301、R301(0R/DNP)、C301(100nF)、C302(10uF)、R302(10k/DNP) | 0 错误 | 电源断开位 + 去耦 + INT 上拉 |
| 04_MPU6050_IMU | J401、R401(0R/DNP)、C401/C402、R402(10k→AD0 接地选 0x68) | 0 错误 | |
| 05_ST7789V_Display | J501(8P)、J502(背光口 2P)、R501/R502(0R/DNP)、C501/C502 | 0 错误 | 背光默认不接裸 LED |
| 06_Power_and_Debug | R601(0R/DNP 源断开)、C601/C602、R603/R604(4.7k/DNP)、R605(10k/DNP)、J601(SWD 5P)、J602(I²C 4P)、TP601–TP605 | 0 错误 | SWD_VTREF 独立网络 |
| 07_ESP32_Radar_Interface | J701(ESP 4P)、J702(雷达 5P)、J703(5V 2P)、J705(转换座 6P)、R701/R702(0R/DNP)、R703/R704(1k)、R705(0R/DNP)、C701/C702 + U701 说明块 | 0 错误 | 雷达链路默认断开 |

所有连接均为 EDA 真实导线 + 命名网络（`W_*` 穿戴 / `B_*` 床边，两套地不互连），
没有使用图片、Mermaid 或文字替代电路。

---

## 2. 已实际完成（在 EDA 内可验证）

- 7 个原理图页全部有内容并已保存（`sense` 工程已写盘）。
- 器件均取自系统库真实器件（LCSC 编号可查），未手捏 UUID：
  - 阻容：0805 `0R`(C17477)、`10k`(C38522)、`4.7k`(C17673)、`1k`(C17513)、`100nF`(C1711)、`10uF`(C2980800)
  - 连接器：`PZ254V-11-xxP` 系列 2/4/5/6/8/12P（2.54mm）
  - 测试点：`TP-黄色测试点`
- DNP（默认不装）器件已在网络与 BOM 中标注：
  R301、R401、R501、R502、R601、R603、R604、R605、R701、R702、R705。
- 每页均执行：`check-unconnected`、`check-shorts`、`check-wire-nets`、`check-pin-shorts`、
  `check-redundant-wires`、`check-duplicates`、`check-wire-through`。

---

## 3. 电气检查结果

**逐页自检：7/7 页全部 0 错误、0 警告。**

**EDA 原生 DRC**：`passed = true`，致命错误 0，非致命提示 3 条：

| 规则 | 内容 | 判断 |
|---|---|---|
| `SHOWDANDLING` | 1 处悬空导线端点（`$1N36`） | 已知：接口网络在连接器侧的命名支线 |
| `ONENETNAME` | `B_RADAR_VIN` 同名网络出现在多段导线上（`$1N32`） | 已知：同一网络由主干 + 两条去耦支线组成 |
| `ATTRMATCHCODE` | 部分器件缺少供应链匹配字段 | 非电气问题，导出 BOM 时以 LCSC 编号为准 |

`check-wire-through` 在 07 页报告 2 条，经放大目视核实为**假阳性**：
该检查把导线的点序列首两点当作直线段，而 EDA 存储的多段线点序并非绘制顺序，
实际渲染为标准 L 形走线（J703 电源入口、R701 附近）。同类假阳性也出现在
`check-overlap`（按包围盒相交判断）。

---

## 4. 交付物

目录：`default-workspace/sensemind_out/`

| 文件 | 大小 | SHA-256(前16) | 说明 |
|---|---|---|---|
| `SenseMind_Hardware_V1_原理图_全集.pdf` | 3.2M | `e8e919c4eda10c5e` | 7 页，由 2400×1711 PNG 合成，**中文完整** |
| `SenseMind_合并BOM.xlsx` | 8K | `3e35d1027c555651` | 21 行，含 DNP 列与备注 |
| `SenseMind_合并BOM.csv` | 4K | `1dc9525040660792` | UTF-8-SIG |
| `SenseMind_Hardware_V1.eprj2` | 464K | `bf39f0111b3155db` | EDA 导出的原生工程 |
| `SenseMind_Board1_netlist.net` | 88K | `5915c58f1d0e3ffd` | 穿戴终端网表（JSON） |
| `SenseMind_Board2_netlist.net` | 36K | `ed9789bba274bfc3` | 床边终端网表（JSON） |
| `src/page01..07.esch` | — | — | 各页 EDA 原始文档源码 |
| `png/` | — | — | 各页 2400×1711 渲染图 |

> 注意：EDA 直接导出的矢量 PDF（`SenseMind_Board1_sch.pdf` 等）中文使用未嵌入的
> SimSun，在无该字体的阅读器中会丢字，因此正式交付采用 PNG 合成的 PDF。

---

## 5. 未完成项与阻塞原因

**U101（nRF52840 模块）与 U701（ESP32 模块）没有库符号。**

实测证据（当前半离线模式）：

| 操作 | 结果 |
|---|---|
| `lib_LibrariesList.getPersonalLibraryUuid()` | 空（个人库未加载） |
| `lib_Symbol.create("project", name)` | 成功返回 uuid |
| `lib_Symbol.openInEditor(...)` | 返回错误对象，编辑器不切换 |
| `lib_Symbol.updateDocumentSource(...)` | 恒返回 `false`，源码不写入 |
| `lib_Symbol.copy(<系统符号> → project)` | 无返回、无产物 |

因此无法创建带引脚的自定义符号。**当前替代方案**：在 02/07 页放置虚线说明块，
完整列出模块已用引脚 → 网络对应关系（含 SWD、P0.13 使能、B_GND 与 W_GND 不共地）。
连接器侧的 12 条 / 4 条命名网络已经画好，符号补齐后只需把模块引脚接到这些网络上。

**影响范围**：ERC 中这些网络目前只有连接器一端；BOM 不受影响（模块本就不贴装）。

---

## 6. 设计前提与待确认清单

| 项目 | 状态 |
|---|---|
| 雷达 UART 数据输出/功能已开放 | **设计前提**（用户指令），非实测 |
| 雷达 UART 逻辑电平、最高输入电压 | **未确认** → 链路默认断开（R701/R702/R705 不装），可经 J705 外接电平转换 |
| nRF 板 3.3V 外设输出能力 | **未核实** → R601 默认断开，需串电流表实测 |
| MAX30102 / MPU6050 / ST7789V 模块实际针序与版本 | **未确认** → 用标准化线束排针，不冻结模块封装 |
| 屏幕背光是逻辑使能还是裸 LED | **未确认** → R502 默认不装，J502 仅供已验证的逻辑驱动 |
| 各模块板载 I²C 上拉 | **未确认** → R603/R604 默认不装，需先查模块 |
| 雷达峰值电流 | 手册仅给平均 80mA，**峰值未知** |
| nRF 板 P0.13/D2/D3 接触稳定性 | 历史记录显示不稳，需上电复核 |

---

## 7. 下一步

1. 切在线模式后：建 U101/U701 符号（无封装、`addIntoBom=false`），把引脚接到已有网络，重跑 DRC。
2. 复核 DNP 清单与上拉电阻的实际装配决策（依赖模块实测）。
3. 机械与封装核对：nRF 排针孔位、模块尺寸、屏幕/PPG 贴肤位置、IMU 方向。
4. 原理图与 DRC 闭环后才做 PCB 布局草案；当前**不准备 Gerber、不标记可生产**。

---

## 8. 复现与环境

```bash
cd '~/Documents/Codex/2026-10-31/eda-sensemind-v1-0-sensemind-pcb'
T='outputs/硬件资料交接/工具/sensemind_draw_cli.py'
python3 "$T" health          # bridge 49620
python3 "$T" page-list
python3 "$T" check-unconnected
python3 "$T" drc
```

实时进度面板：`http://127.0.0.1:8791`（本次会话启动，供观察用）。
