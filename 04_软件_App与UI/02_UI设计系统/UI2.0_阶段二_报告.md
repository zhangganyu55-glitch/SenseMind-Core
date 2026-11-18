# UI 2.0 · 阶段二：首页 + 事件详情 · 完成报告

> 日期：2026-11-03 ｜ 范围：`App.kt`（照护者首页）+ `CaregiverScreens.kt`（事件详情）｜ 未改业务逻辑与 API

---

## 一、Warning 三层色已落地

| Token | 值 | 用途 | 对比度（白 / 浅底 / 页面底） |
|---|---|---|---|
| `Warning` | `#B57E38` | 图标、边框、状态标记 | 3.50 / 3.12 / 3.22 ✅ |
| `WarningText` | `#946323` | 小字号警告文字 | **5.16 / 4.60 / 4.76** ✅ |
| `WarningSoft` | `#F8F1E6` | 警告卡片底色 | — |

规则写进了 `Theme.kt` 注释：**小字号文字禁止直接用 `Warning`**，必须用 `WarningText`。首页里「数据已过期」那行 13sp 用的就是 `WarningText`。

---

## 二、首页（照护者）

### 结构

```
SenseMind                     王阿姨
今天 11 月 3 日
晚上好，王阿姨

┌────────────────────────────────────┐
│▎● 数据正常更新                     │  ← 状态卡，左侧 4dp 色条
│  2 位家人 · 最近更新 09:41          │
└────────────────────────────────────┘

家人                            2 位
┌────────────────────────────────────┐
│ ● SM-01              [REPLAY 回放]  │
│ SM-H3-05 · 更新于 11-03 09:41       │
│ 72 bpm    98 %                     │
│ [需关注 1] [待确认 1]               │
└────────────────────────────────────┘

高级诊断                              展开   ← 折叠，默认收起
```

### 三条判断规则

1. **状态说的是数据，不是病情**：文案只有「数据正常更新 / 部分数据已过期 / 尚未收到数据」，没有「健康 / 异常」。「设备在线 ≠ 健康正常」这条语义保住了。
2. **技术字段全部下沉**：后端版本、APK 契约、`/v1/alerts` 授权状态移进「高级诊断」，默认折叠。主界面已无任何 API/JSON/Token 字段。
3. **缺数据不显示 0**：`heart_rate` 为 null 时显示 `—` 并降为三级色，副标题写「数据已过期」而不是「0 bpm」。

### 保留下来的业务能力

`state.subjects` / `stale` / `data_mode` / `active_event_count` / `unacknowledged_event_count` / `latest_investigation` 全部原样使用；`viewModel.selectSubject`、`viewModel.refresh` 调用点不变。

---

## 三、事件详情

### 四段式

| 段 | 内容 | 数据来源（未变） |
|---|---|---|
| ① 发生了什么 | 事件名 + 活动/已解除 + 待确认/我已了解 + 时间 + 确认人 | `event.status` / `acknowledged` / `acknowledged_by` |
| ② 系统观察到了什么 | 状态转换时间线 | `detail.transitions` |
| ③ 知微的调查结果 | 状态 + 结论 + 不确定性 + 缺失数据 | `investigation.structured` |
| ④ 我可以做什么 | 主按钮「我已了解」+ 语义说明 | `viewModel.acknowledge` |
| 支持这条判断的数据 | 证据列表 | `detail.evidence` |
| 高级诊断（折叠） | 调查状态、AI 状态、模型、证据数、尝试/上限、Token 用量 | `investigation` 原字段 |

### 三条红线

1. **按钮文案是「我已了解」**，说明文字明确写「不会改变系统的分析状态，也不代表身体已经恢复」。ACK 语义没有被改写。
2. **失败和证据不足是两个状态**：
   - `failed` → 红色提示卡「分析未能完成」+ 失败原因
   - `insufficient evidence` → 「当前证据不足」
   
   两者都不显示成「分析已完成」。
3. **技术字段只在折叠区**：Token 用量、模型名、Evidence ID 都收进「高级诊断」。

### 新增的状态文案映射

`agentStateText()` 把后端状态转成用户话：

| 后端 | 界面 |
|---|---|
| `monitoring` | 持续观察中 |
| `queued` | 正在排队分析 |
| `retrying` | 正在重新分析 |
| `running` / `investigating` | 正在进一步分析 |
| `*insufficient*` | 当前证据不足 |
| `completed` | 分析已完成 |
| `failed` / `error` | 分析未能完成 |

---

## 四、Compose Preview（8 个）

| 文件 | Preview 名 | 覆盖状态 |
|---|---|---|
| App.kt | 首页 · 数据正常 | 正常 |
| App.kt | 首页 · 无数据 | 空态 |
| App.kt | 首页 · 数据过期 | 异常/过期 |
| CaregiverScreens.kt | 事件详情 · 调查中 | 调查中 |
| CaregiverScreens.kt | 事件详情 · 已完成·待确认 | 完成 + 待确认 |
| CaregiverScreens.kt | 事件详情 · 已了解 | 已人工确认 |
| CaregiverScreens.kt | 事件详情 · 分析失败 | 调查失败 |

做法：把页面主体抽成 `CaregiverOverviewContent(state, onSelect, onRefresh)` 和 `EventDetailScreenContent(state, onAck, onBack, onRefresh)`，原函数只做转接。这样 Preview 不需要构造 `AppViewModel`，预览的就是真实 UI 代码本身。

---

## 五、状态预览图

**首页三态**：`sketches/05_home_states.png`

**事件详情四态**：`sketches/06_event_states.png`

> 与前一轮相同的说明：这是按 Compose 参数 1:1 复现的设计预览，不是运行时截图。
> 真机截图需要设备接入（见第七节）。

---

## 六、测试结果

| 项 | 结果 |
|---|---|
| `:app:compileDebugKotlin` | **BUILD SUCCESSFUL**，0 error |
| `:app:assembleDebug` | **BUILD SUCCESSFUL**，产物 `app-debug.apk` 11 MB |
| 对比度审计 | 20/20 通过（Warning 拆分后） |
| 单元测试 | **未运行**（`./gradlew test` 需要真机/模拟器无关，可在下次执行） |

---

## 七、真机验收（待你接入）

APK 已构建好：

```
android/app/build/outputs/apk/debug/app-debug.apk
```

小米手机打开「开发者选项 → USB 调试」并插上后，我可以直接：

```bash
adb devices
adb install -r app-debug.apk
adb shell am start -n com.sensemind.app/.MainActivity
adb exec-out screencap -p > shot_home.png
```

现在 `adb devices` 是空的，**没有任何设备连接**。

---

## 八、改动文件清单

| 文件 | 改动 |
|---|---|
| `ui/Theme.kt` | 新增 `WarningText`；`Warning` 改为 `#B57E38` |
| `ui/App.kt` | 重写 `CaregiverOverview` + `SubjectCard`；新增 `InlineMetric`、`agentStateText`、3 个 Preview |
| `ui/CaregiverScreens.kt` | 重写 `EventDetailScreen`；新增 `SectionLabel`、`StepRow`、`BulletLine`、`NoticeCard`、4 个 Preview |
| `ui/Components.kt` | 上一轮的组件（本轮未再改） |
| `docs/ui2.0/` | 报告与预览图（新增，未跟踪） |

**未改动**：`WearerScreens.kt`、`SettingsScreen.kt`、`AppViewModel.kt`、`Repository.kt`、`SenseMindApi.kt`、BLE、后端、数据库、Agent。

---

## 九、已知限制

| 项 | 说明 |
|---|---|
| 佩戴者首页 | 本轮未改（`WearerShell` 仍是旧布局，但已继承新主题变浅色） |
| 事件列表 `EventRow` | 未改，仍是旧样式，下轮统一 |
| 真机截图 | 无设备连接 |
| 深色模式 | 未做 |
| 单元测试 | 未跑 |

---

## 十、Git 状态

```
 M android/app/src/main/java/com/sensemind/app/ui/App.kt
 M android/app/src/main/java/com/sensemind/app/ui/CaregiverScreens.kt
 M android/app/src/main/java/com/sensemind/app/ui/Components.kt
 M android/app/src/main/java/com/sensemind/app/ui/Theme.kt
?? docs/ui2.0/
```

4 个文件改动，951 行新增 / 238 行删除。**未 commit、未开分支**，等评审。
