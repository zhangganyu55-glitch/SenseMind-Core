# SenseMind UI 2.0 · 现状审计

> 审计对象：`~/Downloads/guardian-t12-1.1`（git worktree，分支 `claude/agent3-decision-v0.1.2-t12-1.1`，HEAD `23d19c5`，2026-11-03 21:49）
> 主仓库：`~/Downloads/guardian-angel-agent-starter/.git`
> 审计方式：**只读**。未修改、未 checkout、未 commit 任何文件。
> 审计时间：2026-11-03

---

## 0. 先说清楚这次审计的边界

本轮先派了两个子代理并行审计，**两个都在返回前失败，没有产出**。下面的结论是我直接通读代码得到的，覆盖面如下：

| 已核实 | 未核实（改造前必须补） |
|---|---|
| Android 文件结构与 14 个源文件清单 | `AppViewModel.kt`(372 行) 内部状态机细节 |
| 主题体系（`Theme.kt` 全文） | `Repository.kt` 的缓存/轮询策略 |
| 全部 Composable 清单与职责 | `console.py` 里 1200+ 行 JS 的逐函数行为 |
| 两端 API 调用路径 | 测试文件的实际断言内容 |
| 控制台页面区块结构 | BLE 重连时序 |

标「未核实」的项不影响第一阶段的设计决策，但**动代码前要补齐**。

---

## 1. Git 现状（任务书第九条要求）

| 项 | 值 |
|---|---|
| 当前分支 | `claude/agent3-decision-v0.1.2-t12-1.1` |
| HEAD | `23d19c5` · 2026-11-03 21:49 · `claude: T12-1.1-A: add session and ingestion database foundation` |
| 未提交文件 | **0 个**（工作区干净） |
| 相对 main | 领先 9 个提交 |
| 现存 worktree | 11 个，其中与客户端相关：`sensemind-android-app`(claude/android-app, 0.1.0)、`sensemind-mac-console`(claude/mac-console)、`guardian-t12-1.1`(当前) |

**结论**：本次审计的 worktree 是 Android 0.2.0 / 后端最新的一份，可作为 UI 2.0 的基线。但 `claude/android-app` 与 `claude/mac-console` 两个分支仍在，**改造前必须确认它们是否还有未合并的改动**，否则会在错误的分支上重写。

建议：从 `23d19c5` 拉 `ui/2.0` 分支，不直接在当前分支做。

---

## 2. Android 现状

### 2.1 技术栈

| 项 | 值 |
|---|---|
| 包名 / 版本 | `com.sensemind.app` / 0.2.0 (versionCode 2) |
| 语言 / UI | Kotlin + Jetpack Compose（**不是 Flutter**） |
| 源码规模 | 14 个 `.kt`，3125 行 |
| 外部依赖 | 未逐项核实（下次补 `build.gradle.kts` + `libs.versions.toml`） |

### 2.2 分层

```
com.sensemind.app/
├── MainActivity.kt          入口
├── ble/
│   ├── BleProtocol.kt       分片/ACK/CRC 编解码
│   └── NrfBleClient.kt      扫描/连接/重连
├── data/
│   ├── Models.kt            DTO（Session / Device / Subject / Event / Evidence / Investigation）
│   ├── SenseMindApi.kt      HTTP 客户端（13 个接口方法）
│   ├── Repository.kt        数据装配
│   └── SessionStore.kt      Token/角色持久化
└── ui/
    ├── Theme.kt             颜色 + 字阶（**深色霓虹**）
    ├── App.kt               根壳 + 配对 + 照护者壳 + TabBar
    ├── WearerScreens.kt     佩戴者壳 + 概览 + BLE 页
    ├── CaregiverScreens.kt  对象详情 + 事件详情 + 证据行
    ├── Components.kt        通用组件（13 个）
    └── SettingsScreen.kt    设置
```

### 2.3 页面清单

| # | Compose 入口 | 文件 | 用户看到什么 |
|---|---|---|---|
| 1 | `PairingScreen` | App.kt | 输入配对码，选角色 |
| 2 | `WearerShell` → `WearerOverview` | WearerScreens.kt | 佩戴者：我的数据 |
| 3 | `BleScreen` | WearerScreens.kt | 佩戴者：蓝牙连接 |
| 4 | `CaregiverShell` → `CaregiverOverview` | App.kt | 照护者：家庭成员列表 + 事件 |
| 5 | `CaregiverEvents` | App.kt | 照护者：事件列表 |
| 6 | `SubjectDetailScreen` | CaregiverScreens.kt | 某位家人的详情 + 趋势 |
| 7 | `EventDetailScreen` | CaregiverScreens.kt | 事件详情 + 证据 + 调查 |
| 8 | `SettingsScreen` | SettingsScreen.kt | 设置 / 设备 / 授权 |

导航是**手写状态机**（`AppUiState` + `TabBar`），没有用 Navigation-Compose。改造时可以保留，但页面增多后会难维护。

### 2.4 现有组件（10 个直接对应任务书要求）

| 现有组件 | 文件:行 | 问题 |
|---|---|---|
| `ScreenBackground` | Components.kt | 深色渐变底 |
| `TopBar` | Components.kt | 无品牌位 |
| `SectionCard` | Components.kt | 深色卡片 + 发光边 |
| `MetricTile` | Components.kt | 等宽字显示数值，工程师风格 |
| `Chip` / `DataModeChip` | Components.kt | LIVE/REPLAY/SYNTHETIC 徽标（**必须保留**） |
| `DemoBanner` | Components.kt | 演示模式横幅（**必须保留**） |
| `KeyValue` | Components.kt | 技术键值对，首页应下沉到诊断页 |
| `EmptyState` / `ErrorBanner` | Components.kt | 已有，样式要重做 |
| `PrimaryButton` | Components.kt | — |
| `TrendChart` | Components.kt | 自绘，无第三方图表库 |

**好消息**：任务书要求的 10 个共享组件，现有代码里已有 8 个的雏形（结构在，只是视觉是工程风），不需要从零搭。

### 2.5 主题现状（改造的核心）

`Theme.kt` 全文 55 行，是一个**深色霓虹开发者面板**：

```
DeepBg  #070C12   背景
CardBg  #0D1620   卡片
Teal    #5EEAD4   主色（荧光青）
Cyan    #38BDF8   次色
Violet  #A78BFA   三级色
Coral   #F87171   错误
Ink     #E6F1F5   正文
Muted   #8FA3B0   次要文字
Line    #1E303D   描边
字体：正文 SansSerif，**labelSmall 是 Monospace + 1sp 字距**
```

这正是任务书明确要淘汰的方向（荧光色、发光边框、工程化面板）。**UI 2.0 的主工作量就在这里：整套 token 替换 + 组件重绘。**

### 2.6 角色与权限

后端是唯一授权来源（`docs/client-apps-and-security.md`）：

| 角色 | 上传测量 | 配置发布 | 对象/事件/调查 | 事件确认 |
|---|---|---|---|---|
| `wearer` | ✅ | ❌ | ❌ | ❌ |
| `caregiver` | ❌ | ✅ | ✅ | ✅ |
| `legacy` | ✅ | ✅ | ✅ | ✅ |

App 端**没有角色切换或提权接口**，角色由配对码决定。UI 2.0 可以改角色的呈现方式，**不能改角色的判定逻辑**。

### 2.7 API 调用（Android）

`SenseMindApi.kt` 里 13 个方法：`health` / `exchange` / `me` / `subjects` / `events` / `eventDetail` / `acknowledge` / `measurements` / `alerts` / `revoke` / `setConsent` / `registerDevice` / `postHardwarePacket`。

### 2.8 数据语义红线（来自代码与文档）

1. `EventDto.acknowledged` 只表示**人工已确认**，不表示事件已解决 —— `EventDetailScreen` 现有文案已经是「我已了解」，**改造时不要改成「已处理/已解决」**。
2. `SubjectDto.stale` 表示数据过期，必须显示更新时间，不能只显示「在线」。
3. `EvidenceDto.synthetic` / `DataModeChip` 的 LIVE/REPLAY/SYNTHETIC 必须保留在每条证据上。
4. 缺失值现在用 `—`，**不能改成 0**。

---

## 3. Mac 上位机现状

### 3.1 架构

```
FastAPI（guardian/factory.py）
  ├── GET /console              → CONSOLE_HTML（factory.py:286）
  ├── /v1/console/*             本地控制台专用（不外露给 APK）
  ├── /v1/*                     APK 主接口
  └── /health                  健康检查
```

**没有前端构建链**：整个控制台是 `guardian/console.py` 里一个 55 KB 的 Python 字符串 `CONSOLE_HTML`（`console.py:127` 起），HTML + CSS + JS 全内联。字体、颜色、布局都在这个字符串里。

这是改造的最大特点：**改 UI = 改一个巨大的 Python 字符串**。没有组件化、没有热更新、没有依赖管理。

### 3.2 页面区块（当前）

| 区块 | 标题 | 内容 |
|---|---|---|
| 顶栏 | 知微 SenseMind v0.7 监测控制台 | 连接状态点 + 环回监测 |
| 指标行 | — | 设备总数 / 活动事件 / Agent 调查中 / 待发送告警 / 待人工确认（5 个数字） |
| `#runtime-health` | 系统健康与模型状态 | `/health`、`/v1/runtime/status`、`/v1/ml/status` |
| `#devices` | 设备状态 | 设备卡片列表 |
| `#events` | 事件 | 事件列表 |
| `#trend` | 实时趋势 | 心率 / SpO₂ / 加速度幅值 |
| `#detail` | 证据链与事件闭环 | 事件详情、证据、调查状态 |
| `#toast` | — | 全局提示 |

### 3.3 前端调用的接口

| 前端 fetch | 用途 |
|---|---|
| `/v1/console/snapshot?device_id=*` | 全量快照（设备 + 事件 + 统计） |
| `/v1/console/events/{id}` | 事件详情 |
| `/v1/events/{id}` | 事件（公开接口） |
| `/v1/history?device_id=` | 趋势数据 |
| `/v1/investigations/{id}` | 调查状态机 |
| `/health` `/v1/runtime/status` `/v1/ml/status` | 系统健康 |

### 3.4 现状评价

现在的控制台是**按「排查问题」设计的**，不是按「照护一个人」设计的：

- 首屏 5 个数字（设备总数、待发送告警…）是运维视角，不是家属视角
- 「系统健康与模型状态」占了一整块，普通用户不需要
- 没有「当前在看谁」的概念，要先选设备才出数据
- 没有三栏，没有右侧智微观察位，Agent 调查结果埋在 `#detail` 里

**这些正是任务书第六节要重构的部分。**

---

## 4. 不能破坏的业务功能（红线清单）

| # | 红线 | 依据 |
|---|---|---|
| 1 | `POST /v1/caregiver/events/{id}/ack` 语义 = 人工确认，不改调查状态 | `docs/client-apps-and-security.md` |
| 2 | 角色由后端凭据决定，客户端不得提供提权入口 | 同上 |
| 3 | 跨家庭访问返回 404，UI 不能弱化这一层 | 同上 |
| 4 | LIVE / REPLAY / SYNTHETIC 必须在每条数据上可见 | 同上 + `Components.kt:DataModeChip` |
| 5 | 缺失数据显示 `—`，不得为 0 | `console.py` 趋势区「无样本时明确显示缺失」 |
| 6 | 设备在线 ≠ 健康正常 | `docs/Mac上位机使用说明.md` 数据语义段 |
| 7 | Agent 结论不得把推测说成事实 | 任务书第七节 |
| 8 | 调查失败/证据不足不得伪装成完成 | 同上 |
| 9 | 研发诊断能力（BLE 日志、CRC、token 用量、Evidence ID）必须保留，只是下沉 | 任务书 6.3 |
| 10 | 不改后端 API 契约、不改库表、不改 Agent 逻辑 | 任务书第二节 |

---

## 5. 新旧页面映射表

### Android

| 旧 | 新 | 变化 |
|---|---|---|
| `PairingScreen` | 配对页（保留） | 换皮 + 角色说明人话化 |
| `WearerOverview` | **我的今天**（Home） | 加问候语、状态摘要、知微观察 |
| `BleScreen` | 设备页（下沉） | 从一级页降为「设备」子页 |
| `CaregiverOverview` | **家人首页** | 成员列表改成人物卡 + 今日摘要 |
| `CaregiverEvents` | **事件中心** | 卡片化，加调查状态与确认状态 |
| `SubjectDetailScreen` | **趋势详情** | 今日/7天/30天筛选，数据质量标注 |
| `EventDetailScreen` | **事件详情** | 改成四段式：发生了什么 / 观察到什么 / 调查结果 / 后续 |
| `SettingsScreen` | **设置** | 拆成 家庭·设备·隐私·通知·诊断 |

### Mac

| 旧 | 新 |
|---|---|
| 顶栏 + 5 个统计数字 | 左栏品牌 + 导航；统计数字并入中栏摘要 |
| `#runtime-health` | 移入「设备管理 → 高级诊断」 |
| `#devices` 列表 | 左栏「家庭成员」+ 中栏当前佩戴者卡 |
| `#events` | 中栏「事件时间线」 |
| `#trend` | 中栏「趋势图」 |
| `#detail` | 右栏「知微观察」 |
| — | 新增右栏可折叠 |

---

## 6. 技术风险

| 风险 | 影响 | 处置 |
|---|---|---|
| 控制台是 55 KB 内联字符串 | 改造极易产生巨型 diff，难以 review | 先拆成 `console.html` 模板文件，再改样式 |
| 手写导航状态机 | 页面增多后状态互相污染 | 保持现状，只替换视图层 |
| 无第三方图表库 | 趋势图自绘 | 沿用自绘，统一视觉参数即可 |
| 深色主题硬编码在多个组件里 | 换主题时容易漏 | 先集中到 token，再逐页替换 |
| Android 0.2.0 与 0.1.0 分支并存 | 改错分支 | 从 `23d19c5` 拉 `ui/2.0` |

---

## 7. 结论

- **结构不用动**：两端的数据流、接口、角色、事件闭环都能保留，UI 2.0 是「视图层重写 + 设计系统建立」。
- **主要工作量在 Android**：深色霓虹主题要整体替换，8 个组件要重绘。
- **Mac 的工作量在信息架构**：从「运维面板」重排为「三栏照护中心」，同时把开发诊断整体下沉。
- **下一步**：见 `SENSEMIND_DESIGN_SYSTEM.md`（设计系统 + 关键页面草图）。
