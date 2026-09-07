# Specialist OS 内部分享

目标：工程团队完成首次接入，产品同事选择一个可验证的业务场景。
时间：15 分钟 Slides，10 分钟 Codex 演示。

## 会前准备

在项目目录安装当前版本与 Skill：

```bash
uv tool install --python 3.12 .
npx skills add https://github.com/TsekaLuk/specialist-os --skill specialist-os
```

在新的 Codex 会话中调用 `$specialist-os`。确认 Skill 出现在可用列表。
按本次任务安装模型，使用 Python 3.12。第一次安装与推理可能包括下载和
框架初始化，必须提前完成完整彩排。现场可展示轻量能力的首次安装，重型
模型使用已准备环境，推理时传 `no_cache: true`。

本次本机彩排已通过媒体检查、YOLO、SAM、Depth Anything、PaddleOCR，以及
VAD、whisper.cpp、双说话人分离与 DeepFilterNet 降噪。首次初始化完成后，
视觉五项共 25.0 秒，音频四项约 18.9 秒，均禁用结果缓存。
OmniParser CPU 独立彩排约 24.0 秒，MinerU 约 57.4 秒。
本轮完整结果位于 `output/demo/core15-20260907/index.html`，涵盖 15 个能力族、
56 个 API。Fish S2 已通过本机服务完成合成与克隆；单次约 2 分钟，现场提前发起。
模型下载与首次安装单独计时，不计入上述推理彩排。

按阶段复跑并保存本次证据：

```bash
python scripts/rehearse_demo.py vision
python scripts/rehearse_demo.py audio
python scripts/rehearse_demo.py documents
python scripts/rehearse_demo.py screen
python scripts/rehearse_demo.py document
```

每次运行在 `output/demo/rehearsals/` 创建独立目录，包含请求、CLI 输出、日志与
汇总。只有所有请求成功且未使用缓存时，汇总的 `passed` 才为 `true`。

## 10 分钟主线：把一组业务资料变成可操作结果

| 时间 | 发给 Codex 的提示 | 打开的结果 |
| --- | --- | --- |
| 0:00–1:00 | 使用 $specialist-os，检查视频 docs/assets/e2e/video-input.mp4 的格式、时长和音轨。仅准备本任务需要的本地组件。 | 媒体结构与能力简表 |
| 1:00–3:00 | 对 bus-input.jpg 检测目标，把返回的公交车 bbox 传给 SAM，再生成相对深度图。关闭结果缓存并展示图片。 | 检测框、整车 mask、深度图 |
| 3:00–5:00 | 提取 ocr-table.png 的文字，解析 brief-input.pdf 的表格，再解析 specialist-github-screen.png。 | OCR 区域、文档表格、界面元素 |
| 5:00–7:00 | 转写 meeting-two-speaker.wav 并区分说话人。对 meeting-two-speaker-noisy.wav 降噪，播放处理前后音频。 | 转写、时间线、音频对照 |
| 7:00–8:30 | 打开本轮结果页，按能力族查看检索、人体、身份与几何结果，说明 PnP 的输入对应点与输出位姿。 | 检索排序、关键点、几何结果 |
| 8:30–9:15 | 打开 3D Spatial Lab，依次查看图片生成 3D、单目场景几何与相机标定/PnP。 | GLB、场景表面、棋盘格与相机位姿 |
| 9:15–9:40 | 将检测能力连续调用三次，使用同一批处理和 no_cache=true，展示冷启动与热调用耗时。 | 批处理性能 |
| 9:40–10:00 | 给出把 vision.ocr 接入 Python 项目的最小代码。 | 接入代码与试点场景 |

表中短文件名均位于 `docs/assets/e2e/`。能力之间需要传递结果时，让 Codex
读取上一步的 artifact，通过 SDK 解析本机路径，再发下一条命令。

## 全量能力菜单

视觉：YOLO、SAM、PaddleOCR、Depth Anything、OmniParser、MinerU。
人体：姿态、手部、面部关键点、手势。检索：图像/文本 embedding、相似度、
搜索、相似图。身份：人脸检测、embedding、核验与比较。
音频：VAD、转写、说话人分离、对齐、会议、降噪、Fish Audio 合成与克隆。
算子：全部 geometry、transform 与 media 能力。组合：human_state、measure、
transcribe_video。全量注册表始终用 `specialist capabilities --compact` 获取。

会前全量彩排命令（模型和本地 Fish S2 服务就绪后，输出目录必须是新目录）：

```bash
python scripts/generate_readme_gallery.py --python /absolute/specialist-python --home /absolute/specialist-home --backend real --timeout-seconds 900 --output-dir output/demo/new-rehearsal/assets
python scripts/build_demo_site.py --assets output/demo/new-rehearsal/assets --home /absolute/specialist-home
```

该命令执行所有能力，失败立即退出，并写入 gallery 清单和实际产物。会前核对
清单中全部 56 项为 `ok`。现场十分钟聚焦主线，其余通过结果页与点选问题覆盖。
全量执行可能超出十分钟，不把下载等待隐藏成推理速度。

## 空间实验与几何

本轮已执行相对深度、距离、角度、面积、轮廓、单应、透视变换、相机标定、
PnP 位姿求解、特征匹配及图像 warp。结果页选择“确定性几何与图像处理”查看。
标定与 PnP 使用真实棋盘照片，对应点单位是棋盘格宽度；误差是重投影残差，不能据此宣称恢复了照片场景的真实米制尺寸。

空间实验页位于 `http://127.0.0.1:8742/spatial-viewer/site/`。它展示三条真实
CLI 路线：TripoSR 从椅子照片生成 GLB，MoGe 2 从公交车照片生成可旋转的表面，
以及 OpenCV 多视图标定和第一视图 PnP。TripoSR 约 38.09 秒、MoGe 2 约 3.55 秒，
标定使用 11 张照片，RMS 分别为 0.248 和 0.193 px。生成资产、估计几何和测量
依据有不同语义，仍属于 Core 之外的实验路线，完整记录见 `docs/spatial-watchlist.md`。

ADR-003 保留已有深度与几何能力。重建、SLAM 和生成式 3D 属于实验或可选包方向，
本轮已补充本地可执行 E2E，但不计入 Core 56 项结果。

## 现场节奏

大模型任务超过 45 秒时，说明当前阶段，切到下一个独立任务。已完成彩排的
结果可以标注“彩排结果”展示，并让当前运行继续。失败时展示结构化错误和
恢复步骤。不要把旧产物当成本次生成的结果。

最后邀请工程同事选一个能力接入现有仓库，产品同事提供一份真实材料和期望
结果。后续按准确率、等待时间和人工复核成本判断是否进入产品。

## 性能复现

从仓库根目录运行已验证基础路径（媒体检查和两次目标检测）：

```bash
specialist --backend real --with-dependencies install vision.detect
specialist --backend real --isolate batch examples/demo-batch.json
```

查看每项结果中的 `error`、`performance.cached` 和 `performance.cold_start`。
FFmpeg/ffprobe 需已安装在本机。

```bash
python scripts/benchmark_agent_path.py
```

输出位于 `output/demo/performance.json`。测试条件为本机 CPU YOLO、权重已经
下载、禁用结果缓存。三次独立 CLI 对比同一 runtime 三次调用；这不是首次
安装加速数据，也不是所有模型的性能保证。
