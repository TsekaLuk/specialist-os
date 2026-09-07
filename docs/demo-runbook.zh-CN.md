# LLM 也能做，为什么还要专业模型？

用 Specialist OS 让 Agent 按需调用本地专业能力。

目标：工程团队完成首次接入，产品同事选择一个可验证的业务场景。
时间：15 分钟 Slides，10 分钟 Agent 演示。

主线：通用模型可以参与这些任务，Agent 根据交付要求选择直接处理或调用
专业实现。每个案例说明产物如何进入下一步业务，现场数据不作为 LLM 与
专业模型的同题性能对比。

## 会前准备

在项目目录安装当前版本与 Skill：

```bash
uv tool install --python 3.12 .
npx skills add https://github.com/TsekaLuk/specialist-os --skill specialist-os
```

在支持 Skills 的 Agent 会话中加载 `specialist-os`，确认它出现在可用列表。
其他宿主可通过 CLI 或 MCP 接入，使用各自的工具配置方式。
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

| 时间 | 发给 Agent 的提示 | 打开的结果 |
| --- | --- | --- |
| 0:00–0:30 | 使用 $specialist-os，检查视频 docs/assets/e2e/video-input.mp4 的格式、时长和音轨。仅准备本任务需要的本地组件。 | 媒体结构与能力简表 |
| 0:30–2:15 | 对 bus-input.jpg 检测目标，把返回的公交车 bbox 传给 SAM，再生成相对深度图。关闭结果缓存并展示图片。 | 检测框、整车 mask、深度图 |
| 2:15–3:45 | 提取 ocr-table.png 的文字，解析 brief-input.pdf 的表格，再解析 specialist-github-screen.png。 | OCR 区域、文档表格、界面元素 |
| 3:45–5:15 | 转写 meeting-two-speaker.wav 并区分说话人。对 meeting-two-speaker-noisy.wav 降噪，播放处理前后音频。 | 转写、时间线、音频对照 |
| 5:15–7:15 | 检查开场发起的歌曲工作流，试听 Let's Go Fishin' 原曲、人声与伴奏，查看演唱旋律和六条乐器轨道，再试听生成配乐。 | 歌词、音符时间线、多轨 MIDI、配乐 WAV |
| 7:15–8:00 | 打开本轮结果页，查看检索、人体、身份与几何结果。 | 检索排序、关键点、几何结果 |
| 8:00–9:00 | 打开 3D Spatial Lab，查看图片生成 3D、单目场景几何与相机标定/PnP。 | GLB、场景表面、棋盘格与相机位姿 |
| 9:00–9:40 | 将检测能力连续调用三次，使用同一批处理和 no_cache=true，展示冷启动与热调用耗时。 | 批处理性能 |
| 9:40–10:00 | 给出把 vision.ocr 接入 Python 项目的最小代码。 | 接入代码与试点场景 |

表中短文件名均位于 `docs/assets/e2e/`。能力之间需要传递结果时，让 Agent
读取上一步的 artifact，通过 SDK 解析本机路径，再发下一条命令。

音乐素材位于 `output/music-rehearsal/vibe-ace.ogg`。会前运行：

```bash
.venv/bin/python scripts/rehearse_music.py --python output/music-research/essentia-env/bin/python --notes-python output/music-research/basic-pitch-env/bin/python --separation-python output/music-research/separator-env/bin/python --multitrack-python output/music-research/muscriptor-env/bin/python
.venv/bin/python scripts/build_music_showcase.py
.venv/bin/python scripts/serve_demo.py --port 8744
```

音乐完整交付页：`http://127.0.0.1:8744/music-singing/index.html`，服务支持音频跳转。
包含 Let's Go Fishin' 的原曲、人声／伴奏、ROSVOT 旋律、六个 MuScriptor 乐器轨道，
以及唱段解析、完整转写两条组合工作流。独立 ACE-Step 案例提供 15 秒原创配乐。
完整转写实测 141.83 秒，唱段解析 32.20 秒，带参考音频的配乐生成 36.94 秒，均为关闭缓存、
模型已准备的本机执行。长任务在演示开场发起，解释其他结果时继续运行。

```bash
.venv/bin/python scripts/build_music_showcase.py \
  --source output/music-singing-rehearsal --output output/demo/music-singing \
  --generation output/music-generation-controls --workflows output/music-workflow-rehearsal
```

爵士乐对照页仍保留在 `http://127.0.0.1:8744/music/index.html`。
现场让 Agent 复跑上述命令后刷新页面。图中的音符和可下载 MIDI 来自同一次
Basic Pitch 调用。指纹比较目前演示同一录音的一致性，不作为检索准确率。
接着展示 MuScriptor 的电贝斯、电钢琴、鼓轨道，下载完整多轨 MIDI，并试听分离的
人声／伴奏。此曲为器乐录音，人声轨主要用于检查串音，不把它当作人声分离质量基准。
MuScriptor 本机 MPS 单次约 31 秒，分轨 CPU 约 17 秒，可在解释分析结果时运行。

Slides：`output/demo/slides/final/Specialist-OS-AHA-v5.pptx`，共 17 页、15 分钟。
讲稿：`output/demo/slides/final/Specialist-OS-AHA-v5-Speaker-Notes.md`。
[下载内嵌音频版](slides/Specialist-OS-AHA-v5.pptx) ·
[讲稿](slides/Specialist-OS-AHA-v5-Speaker-Notes.md)。
第 9 页内嵌降噪前后音频，第 12 页内嵌原曲、人声、伴奏和生成配乐。
音频以 MP3 192 kbps 随 PPTX 打包，放映时点击波形播放，无需启动 demo 服务。
演示页保留原始 WAV 和 MIDI 文件。投影前需在实际使用的演示软件中检查播放。

开场先发起完整歌曲工作流，让推理与其他案例讲解交错进行：

```bash
.venv/bin/python scripts/rehearse_music_workflows.py \
  output/music-singing-rehearsal/singing.ogg \
  --home output/music-rehearsal/home --output output/music-workflow-rehearsal
```

生成配乐的带参考音频命令见 [Music 文档](music.md#generation-controls)。
Slides 构建入口为 `scripts/build_aha_slides.mjs`，音频打包入口为
`scripts/prepare_slide_media.py` 与 `scripts/embed_slide_audio.py`。

## 静默录制路径

录制主体是 Codex 接到任务、发现能力、调用真实 CLI、检查输出并打开交付页面的
完整过程。Remotion 负责字幕、局部放大和明确标注的等待加速，保留实际耗时。
不重建聊天或终端，不用结果图轮播替代执行过程。

音乐任务提示：把这首歌做成练习素材，分离人声和伴奏，提取演唱旋律，生成
多乐器 MIDI，整理为可以试听和下载的工作区。保留 CLI 命令和每步产物来源。

静默录制不抢焦点、不采集麦克风或其他应用。模型产物音频直接用于后期，不在
录制时外放。先验证系统能持续捕获被遮挡的 Codex 窗口，再开始正式录制。
Music 验收和交付页面修复完成前不启动录制。

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
