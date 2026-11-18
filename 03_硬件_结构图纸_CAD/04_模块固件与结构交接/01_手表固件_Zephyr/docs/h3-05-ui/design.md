# 知微 SenseMind H3-05 产品化 UI 设计记录

状态：**代码完成、编译通过、离线像素预览通过；最终发布包已烧录，屏幕经接线修复后恢复；A–D 真机测试待完成。**

- 工作分支：`feature/product-ui`（基于 `feature/buttons-ui`，未修改 main）
- H3-04 检查点：`452b82d feat: dual-button band UI (H3-04)`
- H3-05 提交：`8023d05 feat: product-grade four-page band UI (H3-05)` + `67d243c chore: add UI refresh trace and stack headroom`（最终）
- 固件目录：`firmware-display/`
- 目标板：`promicro_nrf52840/nrf52840/uf2`，Zephyr 4.5.0，UF2 bootloader 0.6.0
- 应用区：0x26000–0xAD000（540 KB），bootloader / UICR 未修改

---

## 1. 硬件与 GPIO 核对

### 1.1 ST7789V 240×240

| 屏幕引脚 | 开发板引脚 / 焊盘 | 说明 |
|---|---|---|
| GND | GND | 共地 |
| VCC | 3V3 | 3.3 V |
| SCL | P1.01 / 101 | SPI2 SCK，8 MHz |
| SDA | P1.02 / 102 | SPI2 MOSI |
| RES | P0.11 / 011 | 复位 |
| DC | P1.00 / 100 | 数据/命令 |
| CS | P1.07 / 107 | 片选，低有效 |
| BL | 3V3 | 背光经板载限流电阻，无亮度 GPIO |

显示配置：`spi2`、RGB565、x/y offset 均为 0、`MIPI_DBI_MODE_SPI_4WIRE`、`write-only`，沿用已验证的 H3-04 配置。

### 1.2 两个实体按钮

| 按钮 | GPIO | 焊盘 | 接法 | 配置 |
|---|---|---|---|---|
| KEY_A | P1.04 | 104 | GPIO → 按钮 → GND | 内部上拉，低有效 |
| KEY_B | P1.06 | 106 | GPIO → 按钮 → GND | 内部上拉，低有效 |

按钮驱动沿用 H3-04 已验证实现：

- 30 ms 去抖
- 短按 40–600 ms
- 长按 ≥ 800 ms，长按只发一次
- 600–800 ms 内松开不产生事件
- 长按后松开不再补发短按
- GPIO 中断只 `k_sem_give`，去抖/判定在按钮线程，事件进 `button_msgq`
- 10 ms 轮询兜底，不阻塞传感器采样

### 1.3 未改动的总线

| 功能 | 引脚 | 说明 |
|---|---|---|
| I²C1 SDA | P0.22 / D4 | MAX30102 + MPU6050 |
| I²C1 SCL | P0.24 / D5 |  |
| 外部 VCC 使能 | P0.13 | 保持高电平 |

H1 BLE 协议、CRC16-CCITT-FALSE、8 字节 ACK、鉴权、后端接口均未修改。

---

## 2. 信息架构

四个主页面 + 两个二级数据页 + 快捷菜单：

| 页面 | 枚举 | 分页点 | 进入方式 |
|---|---|---|---|
| 健康总览 | `PAGE_HEALTH` | 第 1 个 | 开机默认 / B 长按 |
| 健康详情 | `PAGE_HEALTH_DETAIL` | 第 2 个 | A 短按或 B 短按 |
| 运动监测 | `PAGE_MOTION` | 第 3 个 | A 短按 |
| 设备信息 | `PAGE_DEVICE` | 第 4 个 | A 短按 |
| 运动数据（二级） | `PAGE_MOTION_DETAIL` | 隐藏 | 运动页 B 短按 |
| 调试（二级） | `PAGE_DEVICE_DEBUG` | 隐藏 | 设备页 B 短按 |
| 快捷菜单 | `PAGE_MENU` | 隐藏 | 任意主/二级页 A 长按 |

A 短按的主循环：健康总览 → 健康详情 → 运动 → 设备 → 健康总览。

---

## 3. 像素级布局

屏幕 240×240，左右安全边距 12 px。颜色使用 H3-05 规范值并经 RGB565 量化：

- 背景 `#080D16`，卡片 `#172130`，卡片高亮 `#202C3E`
- 品牌 `#42E8D2`，主文字 `#F5F7FA`，辅助 `#98A5B5`
- 成功 `#43D9A3`，警告 `#F2B95C`，异常 `#F36B75`
- 分隔线 `#2A3648`，未选中分页点 `#3E4C5E`

字体：10×16（辅助/正文）、15×24（页面标题）、20×32（大数字），均为 Zephyr CFB 的 DroidSansMono 位图字库。没有中文字库，界面采用简洁英文，未加入大型 CJK 字库。

### 3.1 全局

| 元素 | 坐标 / 尺寸 |
|---|---|
| 顶部品牌栏 | y=0–40，背景色 |
| Logo | 32×32 @ (8,4) |
| SenseMind | 10×16 @ (48,6) |
| BAND | 10×16 @ (48,24) |
| BLE 药丸 | 52×22 @ (178,9)，r=11 |
| BLE 状态点 | 圆心 (189,20)，r=4 |
| BLE 文字 | 10×16 @ (197,13)，ON/OFF |
| 顶栏分隔线 | y=40，1 px；页面切换后 350 ms 内为品牌色 |
| 页面标题 | 15×24 @ (12,46) |
| 标题右侧辅助字 | 10×16，右对齐到 x=228，y=50 |
| 分页点 | y=222；圆心 x=99/113/127/141；当前项 12×6 药丸，其余 r=3 |
| 二级页底部提示 | 10×16 居中 @ y=220，`B BACK` |
| 菜单底部提示 | 10×16 居中 @ y=220，`A MOVE    B OPEN` |

### 3.2 健康总览

| 元素 | 坐标 / 尺寸 |
|---|---|
| 心率卡片 | (12,50,216,94)，r=14 |
| HEART RATE | 10×16 @ (26,62) |
| PPG 状态药丸 | (146,59,68,20)，r=10；点 (161,69) r=4；文字 (170,63) `PPG`；点的颜色表示 LIVE/STALE/OFF |
| 心率占位 `--` | 两条 30×8 圆角条，中心 x=120，y=88，间隔 10 |
| BPM | 10×16 居中 @ y=104 |
| RAW PPG ONLY | 10×16 居中 @ y=122 |
| SpO₂ 卡片 | (12,150,104,58)，r=12 |
| SPO2 标签 | (20,156) |
| SpO₂ 占位 `--` | 两条 18×7 条，中心 x=64，y=174，间隔 8 |
| `%` | (88,168) |
| 运动卡片 | (124,150,104,58)，r=12 |
| MOTION 标签 | (132,154) |
| 实时 \|A\| | 20×32 @ (132,170)，如 `1.0` |
| 单位 g | (196,186) |
| 运动状态点 | (216,158)，r=3，按 IMU 数据新鲜度着色 |
| 无 IMU 时 | 两条 18×7 灰条，中心 x=176，y=184 |

### 3.3 健康详情

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `HEALTH` @ (12,46)，右侧 `DETAIL` @ x=168,y=50 |
| HR 卡片 | (12,76,104,52)，r=12 |
| HR 标签 | (20,82) |
| HR 占位 | 两条 12×5 条，中心 x=58，y=98，间隔 4 |
| BPM | (76,94) |
| SpO₂ 卡片 | (124,76,104,52)，r=12 |
| SPO2 标签 | (132,82) |
| SpO₂ 占位 | 两条 12×5 条，中心 x=170，y=98 |
| `%` | (190,94) |
| PPG 卡片 | (12,136,216,68)，r=14 |
| PPG IR 标题 | (24,144) |
| 有效性 | 右对齐 x=216,y=144：VALID / STALE / NO DATA |
| 波形绘图区 | (24,164,192,34)，1 px 边框，网格线 |
| 波形数据 | 最近 120 个 IR 采样，50 Hz，约 2.4 s |

### 3.4 运动监测

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `MOTION` @ (12,46) |
| 主卡片 | (12,76,216,84)，r=14 |
| MOTION 标签 | (24,86) |
| 状态 | 右对齐 x=216,y=86：MONITORING / UNAVAILABLE |
| 姿态图 | 圆心 (58,126)，外环 r=22，内环 r=11，十字线 |
| 姿态点 | 实心 r=5 + 外环 r=8，位置由真实 ax/ay 投影，限幅 ±14 |
| \|A\| 标签 | (104,104) |
| \|A\| 数值 | 20×32 @ (104,122) |
| 单位 g | (168,138) |
| 无 IMU | 两条 16×6 灰条，中心 x=160，y=138 |
| IMU 卡片 | (12,168,104,40)，r=10；标签 (20,172)，值 (20,190) ONLINE/OFFLINE |
| GYRO 卡片 | (124,168,104,40)，r=10；标签 (132,172)，值 (132,190) x.xdps |

运动页不输出 STILL/MOVING 等活动分类；没有可靠分类结果时只显示 `MONITORING`，IMU 不可用时显示 `UNAVAILABLE`。

### 3.5 设备信息

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `DEVICE` @ (12,46) |
| 主卡片 | (12,76,216,132)，r=14 |
| SenseMind Band | (24,84) |
| 品牌点 | (204,92)，r=4 |
| 短设备号 | (24,104)，`ID` + 后 12 位十六进制 |
| 分隔线 | (24,126,192) |
| BLE | 标签 (24,130)，值右对齐 x=216：ON/LINK/OFF |
| IMU / PPG | 标签 (24,150)/(128,150)，值 (68,150)/(172,150)：OK/ERR |
| FW | 标签 (24,170)，值右对齐 x=216 |
| UP | 标签 (24,190)，值右对齐 x=216，HH:MM:SS |

### 3.6 运动数据（二级）

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `MOTION DATA` @ (12,46) |
| 主卡片 | (12,76,216,132)，r=14 |
| 表头 | `ACCEL (g)` (24,84)，`GYRO dps` (136,84) |
| 分隔线 | (24,102,192) |
| 三轴 | y=108/126/144；加速度标签 x=24、值 x=48；陀螺仪标签 x=128、值 x=152 |
| 分隔线 | (24,162,192) |
| \|A\| / AGE | y=170；标签 x=24/128，值 x=58/164 |
| SEQ / OVR | y=190；标签 x=24/128，值 x=58/162 |
| 底部 | `B BACK` |

### 3.7 调试（二级）

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `DEBUG` @ (12,46) |
| 主卡片 | (12,76,216,132)，r=14 |
| BLE | y=82，右对齐：SUB/LINK/OFF |
| SEQ / OVR | y=100 |
| RED / IR | y=118，最近一次 PPG 原始值 |
| BTN / DRP | y=136，按键事件数 / 队列丢弃数 |
| DRAW / STK | y=154，最大整屏刷新 ms / UI 线程剩余栈字节 |
| BOT | y=172，完整 16 位 boot_id |
| ID | y=190，设备 FICR ID 后 16 位十六进制（主页面显示后 12 位） |
| 底部 | `B BACK` |

### 3.8 快捷菜单

| 元素 | 坐标 / 尺寸 |
|---|---|
| 标题 | `QUICK MENU` @ (12,46) |
| 行 1 | (12,86,216,38)，r=12，`Back to main` |
| 行 2 | (12,132,216,38)，r=12，`Health detail` |
| 行 3 | (12,178,216,38)，r=12，`Device info` |
| 选中态 | 品牌色边框 + 高亮卡片 + 左侧 4×20 品牌色竖条 |
| 文字 | 10×16 @ (32, y+11) |
| 底部 | `A MOVE    B OPEN` |

不提供亮度调节：背光 BL 直接接 3V3，无背光 GPIO；菜单中不放置不可用项。

### 3.9 开机启动页

120×120 Logo @ (60,24)；`SenseMind` 20×32 居中 y=158；`BAND` 10×16 居中 y=196；品牌色短线 (100,220,40,3)。显示 1.5 s 后进入健康总览。

---

## 4. UI 状态机

### 4.1 页面转移

| 当前页面 | A 短按 | A 长按 | B 短按 | B 长按 |
|---|---|---|---|---|
| 健康总览 | 健康详情 | 打开菜单 | 健康详情 | 健康总览 |
| 健康详情 | 运动 | 打开菜单 | 健康总览 | 健康总览 |
| 运动 | 设备 | 打开菜单 | 运动数据 | 健康总览 |
| 运动数据 | 设备 | 打开菜单 | 运动 | 健康总览 |
| 设备 | 健康总览 | 打开菜单 | 调试 | 健康总览 |
| 调试 | 健康总览 | 打开菜单 | 设备 | 健康总览 |
| 菜单 | 下一项 | 关闭菜单，回到打开前页面 | 确认选中项 | 健康总览 |

菜单确认：

- `Back to main` → 健康总览
- `Health detail` → 健康详情
- `Device info` → 设备信息

所有转移只修改页面枚举并标记整屏重绘；实际 SPI 绘制发生在 UI 线程，不在 GPIO ISR、BLE 回调或传感器线程中。

### 4.2 刷新策略

- 使用 240×16 的单条带缓冲（7,680 B），共 15 条带；不使用完整 240×240 帧缓冲。
- 页面切换：15 条带全部重绘。
- 常规数据：UI 线程 1 Hz 取快照，只标记发生变化的数据带：
  - 健康总览：PPG 状态药丸 2 条带；运动卡片 4 条带；BLE/传感器状态变化时整屏。
  - 健康详情：波形卡片 5 条带；状态变化时同样 5 条带。
  - 运动：主卡片 + 两个小卡片 9 条带。
  - 设备：仅 UPTIME 所在 1 条带。
  - 调试：数据区 8 条带。
- 快照比较使用 `ppg_total`、IMU 六轴、SEQ/OVR、RED/IR、BLE/传感器标志；无变化不重绘。
- 页面切换时顶栏分隔线以品牌色显示约 350 ms，作为轻量切换反馈；不做滑动/淡入动画。
- PPG 波形使用 120 点环形缓冲，50 Hz 采样、1 Hz 刷新；不在 UI 线程做滤波或心率计算。
- UI 线程 8192 B、优先级 7；按钮线程 2048 B、优先级 6；主采样线程和 BLE 栈优先级更高，SPI 写入不会阻塞采集。
- 启用 `CONFIG_INIT_STACKS` + `CONFIG_THREAD_STACK_INFO`，用 `k_thread_stack_space_get()` 每 30 s 采样 UI 线程剩余栈；调试页 `STK` 显示字节数，`DRAW` 显示最大整屏刷新耗时。
- 没有在 ISR 中调用 SPI，没有在 BLE 回调中绘制。

---

## 5. 真实数据规则

| 显示项 | 来源 / 规则 |
|---|---|
| 心率 | 无已验证算法，固定显示 `--`；绝不生成数值 |
| SpO₂ | 无已验证算法，固定显示 `--`；绝不生成数值 |
| PPG 波形 | MAX30102 真实 IR 采样，120 点环形缓冲 |
| PPG 采集状态 | `ppg_ok` + 最近采样时间：LIVE < 1.2 s，STALE < 5 s，否则 OFF；总览页用 `PPG` 药丸的点颜色表示，详情页用 VALID/STALE/NO DATA 文字 |
| 运动状态 | 只显示 `MONITORING` / `UNAVAILABLE`，不做活动分类 |
| \|A\| | MPU6050 真实三轴加速度矢量模长 |
| 姿态点 | 真实 ax/ay 投影 |
| 陀螺仪 | 真实三轴角速度模长 |
| BLE | 真实 connected / subscribed |
| IMU / PPG | 主循环最近一次读取状态 |
| 固件版本 | `VERSION` = `v0.7.0` |
| 设备号 | FICR DEVICEID |
| Uptime | `k_uptime_get()` |
| SEQ / OVR | H1 包序号 / 缓冲溢出计数 |
| RED / IR | 最近一次 MAX30102 原始值（仅调试页） |
| BTN / DRP | UI 已处理按键事件数 / 按钮队列丢弃数 |
| DRAW / STK | 实测最大刷新耗时 / UI 线程剩余栈 |
| 电量 | 无电量计，不显示 |
| 系统健康结论 | 不显示；传感器在线不等于身体状态正常 |

---

## 6. 构建结果

构建命令（在 `firmware-display/`）：

```sh
export ZEPHYR_BASE=~/Documents/Codex/2026-10-30/wo-xia/work/zephyrproject/zephyr
export PATH=~/Documents/Codex/2026-10-30/wo-xia/work/zephyrproject/.venv/bin:$PATH
west build -b promicro_nrf52840/nrf52840/uf2 -d build -- -DEXTRA_CONF_FILE=real.conf
```

`real.conf` 只包含 `CONFIG_SENSEMIND_TEST_DATA=n`，确保构建不使用测试数据。最终 `.config` 中：

- `CONFIG_SENSEMIND_TEST_DATA` 未设置
- `CONFIG_SENSEMIND_BRINGUP_LOG` 未设置（调试页已提供 UI 统计；不额外打印 1 s 传感器日志）
- `CONFIG_SENSEMIND_BOOTLOADER_CMD=y`
- `CONFIG_INIT_STACKS=y`、`CONFIG_THREAD_STACK_INFO=y`
- `CONFIG_SPI=y`、`CONFIG_DISPLAY=y`、`CONFIG_ST7789V=y`、`CONFIG_I2C=y`、`CONFIG_GPIO=y`
- `CONFIG_BT_DEVICE_NAME="SenseMind-Band"`、`CONFIG_BT_MAX_CONN=1`

构建结果：

| 项目 | H3-04 | H3-05 | 变化 |
|---|---:|---:|---:|
| FLASH | 182,276 B (32.96%) | 195,828 B (35.41%) | +13,552 B |
| RAM | 82,924 B (31.63%) | 87,724 B (33.46%) | +4,800 B |
| UF2 大小 | 365,056 B | 391,680 B | +26,624 B |

- 编译无 warning。
- 新增 15×24 / 20×32 字库为 `const` 数据，位于 Flash；RAM 只增加快照/状态字段（约 0.7 KB）。
- 没有完整帧缓冲；条带缓冲 7,680 B 仍在 RAM 统计内。

### 6.1 烧录包

| 文件 | SHA-256 | 说明 |
|---|---|---|
| `D2-4-4D/firmware-product-ui.uf2` | `a8fcc5f2c75148916d32a730f55fd9d9c6de0a2c8458f676c5d886cccd474102` | H3-05 最终发布包（已烧录） |
| `D2-4-4D/firmware-product-ui-diag.uf2` | `68de41da4528d0b213654ea0e4b578aa678332149b2b47f1c4c65287a51c9c74` | 临时诊断包（UI 心跳/band 日志，非验收包） |
| `D2-4-4D/firmware-buttons-ui.uf2` | `87ddf3d02b9a299bbb11d94c4494268c83361e32fd2bee18e5d73bb46d3a5a04` | H3-04 已实测稳定包 |
| `D2-4-4D/h1-v0.7.0-backup.uf2` | `019e5ff507659af9aaa355cced420c9b648c4bffdbcfa7440df3370b3ff8ba87` | H1 v0.7.0 稳定备份 |

---

## 7. 主要修改文件

- `firmware-display/src/display_ui.c`：完整重写为 H3-05 四页 UI、状态机、脏带刷新、真实数据绑定。
- `firmware-display/src/font_1524.h`：新增 15×24 DroidSansMono 字库。
- `firmware-display/src/font_2032.h`：新增 20×32 DroidSansMono 字库。
- `firmware-display/src/sm_logo_32.h`、`sm_logo_120.h`：Logo 背景由 `#081020` 重新键控为产品背景 `#080D16`，保留品牌图形。
- `firmware-display/prj.conf`：增加 `CONFIG_INIT_STACKS`、`CONFIG_THREAD_STACK_INFO`。
- 未修改：`src/main.c`、`src/sensors.c/h`、`src/wire.c`、`src/buttons.c/h`（H3-04 已实现）、SPI/I²C/按钮 overlay、H1 协议、bootloader、UICR、main 分支。

---

## 8. 已完成的静态验证

- `west build` 成功，0 warning。
- 源码扫描无 `STILL` / `MOVING` / 伪造心率/血氧/电量等模式。
- `CONFIG_SENSEMIND_TEST_DATA` 确认关闭。
- 用与固件完全相同的画布函数、坐标、字库和 Logo 数据做了离线像素预览，检查了四页、两个二级页、菜单、启动页在 240×240 下的边界与文字重叠；预览见 `preview/`。
  - 预览是布局验证，不是真机照片，不能替代实物验收。
- 修正了预览阶段发现的 4 处重叠：运动页 `|A|` 与 `MONITORING`、调试页 `DRAW` 与 `STK`、运动详情页 `GYRO (dps)` 越界、菜单标题与 `SELECT` 相撞。

---

## 9. 待执行的真机测试

以下均未执行，不得在报告中标记为通过。

### A. 按钮与页面

1. A 短按：健康总览 → 健康详情 → 运动 → 设备 → 健康总览。
2. A 长按：任意页面打开快捷菜单；菜单内 A 长按关闭；B 长按回健康总览。
3. B 短按：健康总览 → 健康详情；运动 → 运动数据；设备 → 调试；菜单内确认。
4. 长按后松开不产生短按；长按只触发一次；快速连按不卡死。
5. 记录调试页 `BTN` 计数与 `DRP`。

### B. 传感器回归

1. MAX30102 连续采样，PPG 波形有真实变化，RED/IR 在调试页更新。
2. MPU6050 连续采样，倾斜/移动时姿态点与 \|A\| 变化。
3. 屏幕数据持续更新；心率/血氧始终为 `--`。
4. 心率传感器 LED 正常点亮（H1 初始化未受影响）。

### C. BLE / H1 回归

1. Android App 扫描到 `SenseMind-Band` 并连接。
2. 新 `boot_id` 出现在后端；`source_type=hardware`。
3. H1 分片、CRC、`accepted=true`、8 字节 ACK 正常。
4. 后端持续收到真实数据；不断连、不重复。

### D. 10 分钟 Android 稳定性

需要先换 USB：

- 板子从 Mac 拔下，接充电宝供电。
- 手机插 Mac USB，`adb reverse tcp:8010 tcp:8010`。
- 手机 App 连接 `SenseMind-Band`。
- 测试期间不要同时开 Mac BLE 网关。

记录：

- IMU missing、PPG missing
- `buffer_overruns`
- BLE 断连次数
- H1 上传成功数 / 非 200
- 数据时延
- 调试页 `BTN`、`DRAW`、`STK`
- 与上一轮 Android 零丢包基线对比（121/121 online，IMU/PPG 各 +597，missing 0，overruns 0，1194 次 POST 全 200，0 重复）

---

## 10. 烧录前置确认

- 目标板/镜像：`promicro_nrf52840/nrf52840/uf2`，应用区 0x26000–0xAD000。
- 不修改 bootloader / UICR；UF2 只写入应用区。
- 保留 H3-04 与 H1 v0.7.0 备份（见 6.1）。
- 新固件包含 `boot` 命令，可通过 USB CDC 进入 UF2，也可双击 RST。
- **已按 H3-05 第七阶段要求确认并烧录最终发布包；H3-04 与 H1 v0.7.0 备份保留。**
