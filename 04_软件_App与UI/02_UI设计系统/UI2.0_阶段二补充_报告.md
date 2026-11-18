# UI 2.0 · 阶段二补充：事件列表 + 佩戴者首页

> 日期：2026-11-03 ｜ 在阶段二基础上补齐剩余两个页面

---

## 一、底部导航改成批准的四个入口

`CaregiverShell` 现在是 **首页 / 家人 / 事件 / 我的**：

| Tab | 内容 | 说明 |
|---|---|---|
| 首页 | 状态卡 + 第一位家人的指标卡 + 最近 3 条事件 | 只回答「今天有没有事」 |
| 家人 | 全部家人卡片 + 折叠的高级诊断 | 名单页 |
| 事件 | 通知 + 规则事件列表 | 卡片式 |
| 我的 | `SettingsScreen`（未改） | |

佩戴者侧是 **首页 / 设备 / 我的**（本来就没有「家人」这个角色）。

---

## 二、事件列表 `EventRow`

从「一排徽标」改成**卡片 + 左侧 3dp 等级色条**：

```
┌──────────────────────────────────────────┐
│▎心率偏高（实验规则）      [活动中][待确认] │
│  SM-01 · 11-03 10:12                     │
│  正在进一步分析                            │
└──────────────────────────────────────────┘
```

三条规则：

1. **两个徽标语义分开**：左边是事件状态（活动中/已解除），右边是确认状态（待确认/我已了解），不再混在一个 Chip 里。
2. **调查状态单独一行**，用 `agentStateText()` 转换，失败显示「分析未能完成」。
3. **没有调查记录时**明确显示「暂无调查」，不留空。

---

## 三、佩戴者首页

```
SenseMind                          李叔
我的设备

┌────────────────────────────────────┐
│▎● 数据正常上传                      │
│  1 台设备已注册                      │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│ ● SM-01              [LIVE 硬件来源] │
│ SM-H3-05 · 1.2.3                    │
│ 72 bpm    98 %                      │
│ [已上传 128 条] [最近 11-03 09:41]   │
└────────────────────────────────────┘

上传说明与诊断                      展开
```

变化：

- 「数据上传路径」这两段技术说明（`/v1/hardware/packets`、BLE ACK、固件重发）**移进折叠区**
- 「当前没有真实 nRF 设备时，不伪造 BLE 连接或 Live 数据」这条保留，用 `WarningText` 强调
- 未注册设备时给主按钮「注册本机设备」，不再是一句干巴巴的空态
- 数据模式徽标（LIVE/REPLAY/SYNTHETIC）逐条保留

---

## 四、新增 Preview（4 个）

| 文件 | Preview | 状态 |
|---|---|---|
| App.kt | 首页 · 数据正常 / 无数据 / 数据过期 | 3 个（阶段二已有） |
| App.kt | 事件列表（通过 `EventRow` 组合） | 由 `CaregiverEvents` 渲染 |
| WearerScreens.kt | 佩戴者首页 · 已上传 | 有设备有数据 |
| WearerScreens.kt | 佩戴者首页 · 无设备 | 空态 |

做法同前：`WearerOverview` 拆成 `WearerOverview(state, viewModel)` + `WearerOverviewContent(state, onRefresh, onRegister)`，Preview 调后一个，预览的就是真实 UI 代码。

---

## 五、预览图

`sketches/07_event_list_and_wearer.png`：事件列表（有/空）、佩戴者首页（有数据/无设备）

---

## 六、编译与打包

```
:app:compileDebugKotlin  BUILD SUCCESSFUL
:app:assembleDebug       BUILD SUCCESSFUL
app-debug.apk            11 MB
```

---

## 七、改动文件

| 文件 | 改动 |
|---|---|
| `ui/App.kt` | 四标签外壳、`CaregiverHome`、`CaregiverFamilyTab`、`StatusSummaryCard`、新 `CaregiverEvents`、新 `EventRow`、新 `TabBar` |
| `ui/WearerScreens.kt` | 新 `WearerShell`（3 tab）、新 `WearerOverview` + `WearerOverviewContent`、2 个 Preview |
| `ui/Theme.kt` | 同阶段二（Warning 三层色） |
| `ui/Components.kt` | 未再改 |

**未改动**：`SettingsScreen.kt`、`BleScreen`（函数体未动，只跟随主题变浅色）、`AppViewModel.kt`、`Repository.kt`、`SenseMindApi.kt`、BLE 逻辑、后端、数据库、Agent。

---

## 八、已知限制

| 项 | 说明 |
|---|---|
| `BleScreen` 视觉 | 仍是旧布局，只随主题变浅；它本身是技术页，下轮单独处理 |
| `SettingsScreen` | 未改 |
| 事件列表分页 | 无，后端返回多少显示多少 |
| 真机截图 | 仍无设备连接 |
| 单元测试 | 未运行 |

---

## 九、Git

```
 M App.kt  M CaregiverScreens.kt  M Components.kt  M Theme.kt  M WearerScreens.kt
?? docs/ui2.0/
```

5 个文件改动，未 commit、未开分支。
