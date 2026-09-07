# LLM 也能做，为什么还要专业模型？

用 Specialist OS 让 Agent 按需调用本地专业能力

15 分钟分享，10 分钟现场演示

第 9 和 12 页内嵌音频，放映时点击波形播放。

## 1. LLM 也能做，为什么还要专业模型？

0:00–0:35

用 Specialist OS 让 Agent 按需调用本地专业能力。通用模型已经可以看图、读文档、理解音频，也可以写代码或调用工具完成很多专业任务。今天讨论的是如何组织这项工作：什么时候直接用通用模型，什么时候让 Agent 调用一个专用实现。我们从任务需要交付的结果出发，看本地模型与算子怎样加入 Agent 的工作流。十五分钟分享之后，用十分钟看实际运行。工程同事可以沿用相同接口接入项目，产品同事可以把自己的业务材料带入这些路径。

资料来源：用户确认的分享主题；README.md；skills/specialist-os/SKILL.md

Logo：docs/assets/brand/specialist-os-logo-b-transparent.png，源自 Logo B

## 2. 不同执行路径

0:35–1:30

能理解一份材料，与怎样把结果交给下一个系统，是两个相连的设计问题。通用模型可以直接回答，也可以生成代码、组织工具调用。专用实现提供既定的输入输出：图像编辑需要 mask，文档入库需要区域和表格，录音检索需要时间线，编曲需要 MIDI。Agent 可以沿用这些实现，把结果拿回来继续推理与交互。这里没有把某类输出说成 LLM 永远做不到，而是展示可以复用的执行路径。

资料来源：registry/models.yaml；本 deck 对应的视觉、文档、语音和音乐 CLI 证据

## 3. Agent 的专业能力层

1:30–2:25

LLM 理解目标，Agent 决定哪些步骤直接完成，哪些步骤交给工具。Specialist OS 把专业模型和确定性算子做成统一的能力接口，负责依赖准备、模型管理与隔离执行。结果回到 Agent 后，它可以解释结果、请求复核或继续下一步。宿主只要具备相应的 CLI 或 MCP 工具调用能力，就可以接入这条路径。Skill 是发现和调用说明，业务代码也可以直接使用 SDK 或 HTTP。

资料来源：docs/architecture.md；specialist/runtime.py；specialist/providers/base.py；skills/specialist-os/references/integration.md

## 4. 能力版图

2:25–3:30

Core 固定为 15 个能力族、56 个 API，包含算子和组合能力。选择时先问业务需要什么输出，再决定模型。ADR-003 保留深度估计、相机标定与 PnP 等已有算子，空间重建留在实验路线，生成式 3D 留在可选重型包路线。近期投入集中在安装、性能与调用质量。模型许可证和硬件要求按实际选中的提供方检查。Fish S2 使用独立本机服务。

资料来源：specialist/core.py；registry/models.yaml；docs/adr/003-defer-spatial-3d-core.md

## 5. 视觉案例

3:30–4:25

两幅图来自本轮 CLI 结果。检测定位人和车辆，再将公交车框传给 SAM 提取整车区域。深度图补充前后层次，适合区域排序。业务可围绕目标建立复核或素材处理流程。深度属于相对估计，真实尺寸测量需要额外标定与尺度依据。现场会重新运行这条路径，展示原图与结果。

资料来源：output/demo/core15-20260907/assets/vision-detect.json；vision-segment.json；vision-depth.json

## 6. 文档案例

4:25–5:20

左侧是本轮 PaddleOCR 返回的 124 个文字区域，位置与置信度支持字段复核。MinerU 本轮处理了 10 页论文，提取 9 张表格，耗时 0.0 秒。正文、公式和表格可以分别进入知识检索与数据校验流程。现场打开解析结果，选择一张表格与原文核对。工程接入时，字段质量应使用自己的业务样本评估。

资料来源：output/demo/core15-20260907/assets/document-parse.json；output/demo/rehearsals/20260907T030519.523169Z/stdout.json

## 7. 界面案例

5:20–6:10

左侧展示本轮 OmniParser 标注结果，共 120 个元素，包含文本、图标、坐标和置信度。独立 CPU 彩排约 24 秒。Agent 可以借此定位搜索栏或文件入口，再交给自动化工具操作并重新观察。产品机会包括界面知识提取和测试辅助。

资料来源：output/demo/core15-20260907/assets/screen-parse.json；output/demo/rehearsals/20260907T030813.425434Z/summary.json

## 8. 空间能力

6:10–7:05

三类空间结果分别对应生成资产、估计几何和可测量的相机依据。它们都由本机 CLI 执行，输出保留输入、模型、设备、耗时和哈希。实验路线不改变 Core 15。

资料来源：output/demo/spatial/triposr-chair-01/result.json；output/demo/spatial/moge2-bus-03/result.json；output/demo/spatial/chessboard-01/summary.json

## 9. 音频案例

7:05–8:00

这里用的是一段二十秒的故障讨论，内容涉及结账失败、支付回调和回滚。VAD 先给出语音区间，Whisper 提供转写，pyannote 将发言分成两位说话人的四个片段。DeepFilterNet 对带噪版本输出新的音频文件。这样的结果可以进入会议检索、客服回访或事件复盘。说话人标签是自动分组，不代表实名身份。现场会播放处理前后音频，并打开转写与时间线，不需要让听众阅读整个 JSON。

资料来源：本次音频彩排 output/demo/rehearsals/20260907T020603.536311Z/stdout.json；输入 meeting-two-speaker.wav 与 noisy 版本

## 10. 音乐素材

8:00–9:05

Music 扩展包把音乐文件变成可查询的素材信息。这里使用 Kevin MacLeod 的 Vibe Ace，许可 CC BY 3.0。本机 Essentia 输出 BPM 129.70 和 E major，这是模型估计，尚未用标注数据评估准确率。Chromaprint 对同一录音进行指纹比较，是同源素材核对的基础，不是音乐风格相似度。产品可先验证素材编目与剪辑选曲场景。所有数值来自同一输入的实际 CLI 结果。

资料来源：output/music-rehearsal/manifest.json；00-music-analyze.json；03-music-compare_recording.json；https://freemusicarchive.org/music/Kevin_MacLeod/Jazz_Sampler/Vibe_Ace

## 11. 音乐转写

9:05–10:10

同一段 Vibe Ace，Basic Pitch 返回 380 个音符，用于旋律草稿。MuScriptor 输出电贝斯、电钢琴、鼓三个轨道，共 1063 个音符，本机 MPS 用时 31.29 秒。图表直接统计本次各轨道的音符数量，页面提供完整和分轨 MIDI。audio-separator 用时 16.97 秒，返回人声和伴奏 WAV。该曲是器乐录音，人声轨可检查串音，不能据此判断人声分离准确率。现场先听原曲，再检查轨道、下载 MIDI。MuScriptor 属实验能力，权重为非商业许可，MIDI 未作乐谱量化。应用场景包括编曲草稿、练习素材和素材整理。

资料来源：output/music-rehearsal/manifest.json；05-music-transcribe-multitrack.json；06-music-separate.json；https://huggingface.co/MuScriptor/muscriptor-medium

## 12. 音乐组合与生成

10:10–11:00

用同一首带人声与伴奏的完整录音演示练习素材。唱段解析先转换音频格式，再调用 Whisper、ROSVOT 和 Essentia，将歌词片段与音符按时间重叠建立关联。完整转写保留 MuScriptor 乐器轨道，再分离音源，用 Basic Pitch 和 ROSVOT 细化相应音轨。各步骤的结果和来源都保留。ACE-Step 使用独立提示词与 Vibe Ace 参考音频生成十五秒配乐，固定种子 42，指定 100 BPM 与 C major。BPM 与调性是生成条件，输出是否精确遵循需要另行测量。本机模型已准备，所有结果关闭缓存。现场打开 music-singing 页面试听原曲、人声、伴奏和生成配乐，再下载 MIDI。

资料来源：output/music-workflow-rehearsal/manifest.json；output/music-generation-controls/manifest.json；output/music-singing-rehearsal/manifest.json

## 13. Agent Skill

11:00–11:45

Skill 的目标是让新用户只描述任务，不必先熟悉几十个模型。第一次调用先确认 CLI，再查紧凑能力列表，只为选中的能力读取完整格式。安装使用已经验证的 Python 3.12，模型与依赖按任务下载到本机。连续请求可以用批处理复用 worker，跨多轮 Agent 对话可以用持久 MCP 服务。第一次下载与框架初始化要单独展示进度。MinerU pipeline 和 Fish S2 这类额外模型服务需要明确准备，不能把环境未就绪说成已可运行。

资料来源：skills/specialist-os/SKILL.md；specialist capabilities --compact；docs/deployment.md

## 14. 性能实测

11:45–12:20

三次独立 YOLO CPU 调用合计 6.02 秒，批处理共 2.00 秒，加速 3 倍。权重已下载，结果缓存关闭，比较的是启动与执行开销。批处理中后两次推理为 50 和 49 毫秒。能力简表输出减少约 93%。本次独立视觉主线为 25.0 秒，音频主线为 18.9 秒。不同模型应分别测量。

资料来源：scripts/benchmark_agent_path.py；output/demo/performance.json；output/demo/rehearsals/20260907T030519.523169Z/summary.json；output/demo/rehearsals/20260907T030746.572431Z/summary.json

## 15. 工程接入

12:20–13:15

工程接入从一个能力开始。这里省略了 import 和安装步骤，代码表达的重点是显式使用 real backend、开启隔离并在结束时关闭 runtime。完整例子在 Skill 的 integration 参考文件里。短任务用 CLI 很直接，Python 项目可以持有 runtime，Agent 长会话适合 MCP，跨进程服务可以用 HTTP。业务代码还要处理 error、置信度和产物引用。服务部署时保持本地监听，需要跨机器时配置认证与明确的数据策略。

资料来源：skills/specialist-os/references/integration.md；docs/deployment.md；specialist/runtime.py

## 16. 什么时候值得调用

13:15–14:05

专业模型是 Agent 可以选择的工具。对特定产物和重复流程，可以复用一个验证过的专业实现。希望数据留在本机时，还需要结合硬件、首次安装和模型许可判断。对开放理解与例外处理，通用模型仍承担重要角色。最终用同一批业务材料比较候选路径，统计质量、端到端等待时间、资源消耗和人工复核量。前面的 YOLO 数据比较的是两种本地执行方式，没有进行专业模型与 LLM 的同题成本或质量对照，因此不能据此给出普遍优劣结论。

资料来源：用户确认的主题与任务分工原则；output/demo/performance.json；registry/models.yaml

## 17. 现场演示

14:05–15:00

现在切换到具备本地工具调用能力的 Agent。先从用户目标开始，让 Agent 查能力、执行任务，再展示可用结果。每个案例回答同一个问题：用户下一步拿这个产物做什么？视觉展示检测框、mask 和深度，文档展示表格和位置，语音展示播放定位，音乐展示音符与 MIDI。所有现场请求关闭结果缓存。某个任务超过预定时间，就转到独立步骤并保留当前运行状态。最后展示相同能力接口怎样接入现有项目。

资料来源：docs/demo-runbook.zh-CN.md；scripts/rehearse_demo.py；scripts/rehearse_music.py