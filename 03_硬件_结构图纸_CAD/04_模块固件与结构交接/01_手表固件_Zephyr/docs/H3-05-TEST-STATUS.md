# H3-05 当前测试状态

日期：2026-11-02

## 代码与镜像

- 分支：`feature/product-ui`
- 代码提交：
  - `452b82d feat: dual-button band UI (H3-04)`
  - `8023d05 feat: product-grade four-page band UI (H3-05)`
  - `67d243c chore: add UI refresh trace and stack headroom`
- 最终发布 UF2：`../firmware-product-ui.uf2`
- SHA-256：`a8fcc5f2c75148916d32a730f55fd9d9c6de0a2c8458f676c5d886cccd474102`
- 临时诊断 UF2：`../firmware-product-ui-diag.uf2`
- 诊断 UF2 SHA-256：`68de41da4528d0b213654ea0e4b578aa678332149b2b47f1c4c65287a51c9c74`
- 构建：Zephyr 4.5.0，`promicro_nrf52840/nrf52840/uf2`，FLASH 195,828 B（35.41%），RAM 87,724 B（33.46%），编译无 warning
- 配置：`CONFIG_SENSEMIND_TEST_DATA` 关闭，`CONFIG_SENSEMIND_BRINGUP_LOG` 关闭，UI 线程栈 8192 B

## 已经完成的验证

- 代码静态检查：无 `STILL`/`MOVING`/伪造心率/血氧/电量模式。
- 离线像素预览：四个主页面、两个二级页、菜单、启动页；修正了 4 处重叠。预览见 `h3-05-preview/`。
- 最终发布包已烧录，串口正常输出 `*** Booting Zephyr OS build v4.5.0 ***`。

## 屏幕异常排查记录

现象：H3-05 首次烧录后出现花屏，随后全黑。

诊断：

- 主循环仍能响应 `boot` 命令，说明系统没有整体死机。
- 临时诊断固件（`CONFIG_SENSEMIND_BRINGUP_LOG=y`，UI 栈 8192）串口显示：
  - UI 线程每秒执行 `SM UI tick`；
  - `SM UI flush y=144/160/176/192` 均返回 `rc=0`；
  - 主循环持续 `imu_err=0 ppg_err=0 imu=1 ppg=1`；
  - 无 HardFault 输出。
- 结论：固件 UI 线程和 SPI 写路径正常，问题在屏幕接线/供电；用户重新接好后屏幕恢复正常。
- 具体是哪一根线/接触点尚未记录，待用户确认后补充。

## 测试进度

| 测试 | 状态 |
|---|---|
| 编译 / 静态检查 / 离线布局预览 | 完成 |
| Test A：按钮与页面 | 进行中，待逐步记录 |
| Test B：传感器回归 | 待执行 |
| Test C：BLE / H1 回归 | 待执行（需要手机） |
| Test D：10 分钟 Android 稳定性 | 待执行（需要换 USB/充电宝、adb reverse、后端） |

## 下一步

1. 在最终发布包上逐项确认 A/B 短按、长按、菜单、分页点、DEBUG 页 `BTN/DRAW/STK`。
2. 确认 PPG 波形、姿态点、|A|、RED/IR、心率传感器 LED。
3. 手机接 Mac，`adb reverse tcp:8010 tcp:8010`，连接 `SenseMind-Band`，验证新 boot_id、H1 ACK、后端真实数据。
4. 板子接充电宝、手机接 Mac，做 10 分钟稳定性测试，记录 IMU/PPG missing、buffer_overruns、BLE 断连、上传成功、时延、BTN/DRAW/STK，并与此前 Android 零丢包基线对比。

## 备份

| 文件 | SHA-256 |
|---|---|
| `../h1-v0.7.0-backup.uf2` | `019e5ff507659af9aaa355cced420c9b648c4bffdbcfa7440df3370b3ff8ba87` |
| `../firmware-buttons-ui.uf2` | `87ddf3d02b9a299bbb11d94c4494268c83361e32fd2bee18e5d73bb46d3a5a04` |
| `../firmware-product-ui.uf2` | `a8fcc5f2c75148916d32a730f55fd9d9c6de0a2c8458f676c5d886cccd474102` |
| `../firmware-product-ui-diag.uf2` | `68de41da4528d0b213654ea0e4b578aa678332149b2b47f1c4c65287a51c9c74` |
