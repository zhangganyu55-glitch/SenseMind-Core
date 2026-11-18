# 第三方组件、数据与许可说明

本仓库中**项目自有**的代码、图纸、文档以 [MIT License](LICENSE) 发布。
以下为仓库中出现的**第三方内容**及其归属。

---

## 一、代码依赖（运行时不随仓库分发，需自行安装）

| 组件 | 用途 | 许可 | 来源 |
|---|---|---|---|
| FastAPI / Uvicorn | 智能体 HTTP 服务 | MIT | https://github.com/fastapi/fastapi |
| Pydantic | 输入校验与数据模型 | MIT | https://github.com/pydantic/pydantic |
| pytest | 测试 | MIT | https://github.com/pytest-dev/pytest |
| numpy / scipy / scikit-learn | 信号处理与机器学习 | BSD-3-Clause | https://scipy.org / https://scikit-learn.org |
| build123d / OpenCASCADE | 参数化结构建模 | Apache-2.0 / LGPL-2.1 | https://github.com/gumyr/build123d |
| trimesh / matplotlib / PyMuPDF | STL 处理与出图 | MIT / PSF / AGPL（PyMuPDF） | 各自项目主页 |
| Blender | 渲染图生成（可选） | GPL | https://www.blender.org/ |
| Zephyr RTOS | 手表固件（nRF52840） | Apache-2.0 | https://zephyrproject.org/ |
| Jetpack Compose | Android UI | Apache-2.0 | https://developer.android.com/jetpack/compose |
| DeepSeek API | 智能体大模型推理（运行时配置 Key） | 商业服务条款 | https://platform.deepseek.com/ |

> 依赖清单以实际 `requirements.txt` 与 Gradle / CMake 构建文件为准，上表仅列主要项。
> 注意 PyMuPDF 为 AGPL：只在生成图纸的辅助脚本中使用，不参与运行时服务。

---

## 二、数据（**不随仓库分发**）

| 数据 | 用途 | 许可 / 获取方式 |
|---|---|---|
| PPG-DaLiA（UCI） | PPG 心率/呼吸研究回放 | 自行从 UCI 机器学习库下载并遵守其条款 |
| PAMAP2（UCI） | 活动识别模型训练 | 同上 |
| SenseMind 雷达实测数据 | 本项目自采 | **含真实受试者生理信号，未收录**；对外分享前需脱敏并取得知情同意 |

仓库中的 `experiments/`、`runs/`、`docs/*.json` 只有指标与运行记录，不含原始生理波形。

---

## 三、硬件与器件资料

| 内容 | 位置 | 版权 |
|---|---|---|
| 嘉立创 EDA（EasyEDA Pro）工程文件 | `02_硬件_原理图与PCB/` | 工程为本项目绘制；软件归嘉立创 |
| 器件手册（MAX30102、MPU6050、ST7789、nRF52840、ESP32、LD6002 等） | **未收录** | 归各原厂所有，请从官方渠道获取 |
| 系统字体（PingFang SC / STHeiti / Noto Sans 等） | **未收录** | 归各字体权利人；`mkfont.py` 仅在本机裁剪，不随仓库分发 |

---

## 四、商标

"SenseMind"、"知微"、"Guardian Angel" 为项目名；"嘉立创"、"Blender"、"DeepSeek"、"Zephyr"、"Android" 等为各自商标，此处仅作说明性使用。

---

## 五、合规提醒

1. **不是医疗器械**：本项目未做临床验证，不得用于诊断、治疗或紧急报警。
2. **健康数据**：真实受试者的雷达/PPG 记录属敏感个人信息，任何二次采集都应先去标识化并取得书面同意。
3. **凭据**：`.env` 已在 `.gitignore` 中拦截。若你在自己的分支里提交过 Key，请立即在服务商侧轮换。
4. **专利**：本仓库不含专利附图；如需在公开场合引用结构方案，请先确认申请状态。
