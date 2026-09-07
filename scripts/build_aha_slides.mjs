import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const { Presentation, PresentationFile } = await import(path.join(process.env.RUNTIME_NODE_MODULES, '@oai/artifact-tool/dist/artifact_tool.mjs'));

const root = process.cwd();
const skill = process.env.PRESENTATIONS_SKILL_DIR;
const runtimePython = process.env.RUNTIME_PYTHON;
if (!skill || !runtimePython) throw new Error('Set PRESENTATIONS_SKILL_DIR, RUNTIME_PYTHON and RUNTIME_NODE_MODULES from workspace dependencies');
const workspaceDir = path.join(root, 'output/demo/slides');
const build = path.join(workspaceDir, 'build/aha-music-v5');
await fs.mkdir(build, { recursive: true });
const { finalizePresentation } = await import(path.join(skill, 'container_tools/artifact_tool_utils.mjs'));
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { ink: '#2B3034', lime: '#BED600', green: '#28624A', gray: '#596268', pale: '#F0F3F2', white: '#FFFFFF' };
const font = 'PingFang SC';
const read = async file => JSON.parse(await fs.readFile(path.join(root, file), 'utf8'));
const vision = (await read('output/demo/rehearsals/20260907T030519.523169Z/stdout.json')).results;
const audio = (await read('output/demo/rehearsals/20260907T030746.572431Z/stdout.json')).results;
const perf = await read('output/demo/performance.json');
const screen = await read('output/demo/core15-20260907/assets/screen-parse.json');
const doc = await read('output/demo/core15-20260907/assets/document-parse.json');
const durations = [35,55,55,65,55,55,50,55,55,65,65,50,45,35,55,50,55];
const musicManifest = await read('output/music-rehearsal/manifest.json');
async function musicResult(capability) {
  const record = musicManifest.records.find(r => r.capability === capability && r.status === 'ok');
  if (!record) throw new Error(`Missing Music evidence: ${capability}`);
  const envelope = await read(`output/music-rehearsal/${record.result}`);
  if (envelope.error || envelope.performance.cached || envelope.input.sha256 !== musicManifest.fixture.sha256) throw new Error(`Invalid Music evidence: ${capability}`);
  return envelope;
}
const musicAnalysis = await musicResult('music.analyze');
const musicNotes = await musicResult('music.transcribe_notes');
const musicTracks = await musicResult('music.transcribe_multitrack');
const musicStems = await musicResult('music.separate');
const speaker = [];
const media = await read('output/demo/slides/build/media/manifest.json');
async function player(slide, id, label, x, y, width, dark=false) {
  const item = media.find(item => item.id === id);
  text(slide, label, x, y, width, 36, 24, dark ? C.white : C.ink, true);
  slide.images.add({blob:new Uint8Array(await fs.readFile(item.poster)),contentType:'image/png',alt:`audio:${id}`,fit:'contain',position:{left:x,top:y+44,width,height:54}});
}

function text(s, value, x, y, w, h, size=28, color=C.ink, bold=false) {
  const t = s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  t.text = String(value);
  t.text.style = {typeface:font,fontSize:size,color,bold,autoFit:'none'};
  return t;
}
function add(title, dark=false) {
  const s = p.slides.add();
  s.background.fill = dark ? C.ink : C.white;
  text(s,title,64,45,1152,94,46,dark?C.white:C.ink,true);
  text(s,String(p.slides.items.length).padStart(2,'0'),1166,667,50,28,18,dark?C.lime:C.gray);
  return s;
}
async function img(s,file,x,y,w,h) {
  s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,file))),contentType:file.endsWith('.jpg')?'image/jpeg':'image/png',alt:file,fit:'contain',position:{left:x,top:y,width:w,height:h}});
}
function table(s,values,x,y,w,h,widths,size=25) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});
  t.borders.assign({style:'solid',fill:'#D7DFDB',width:0.6});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({
    textStyle:{typeface:font,fontSize:size,color:C.ink},margins:{top:12,bottom:10,left:16,right:12},anchor:'center',
  });
  for(let r=0;r<values.length;r++){
    t.rows[r].height=h/values.length;
    for(let c=0;c<values[0].length;c++){
      const cell=t.getCell(r,c);
      cell.fill=r===0?C.ink:r%2===0?C.pale:C.white;
      cell.text.style={typeface:font,fontSize:size,color:r===0?C.white:C.ink,bold:r===0,autoFit:'none'};
    }
  }
  return t;
}
function note(s,title,body,sources) {
  const index=p.slides.items.length-1;
  const start=durations.slice(0,index).reduce((a,b)=>a+b,0);
  const clock=n=>`${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;
  const content=`${clock(start)}–${clock(start+durations[index])}\n\n${body}\n\n资料来源：${sources}`;
  s.speakerNotes.textFrame.setText(content);
  speaker.push(`## ${index+1}. ${title}\n\n${content}`);
}

let s=p.slides.add();
await img(s,'docs/assets/brand/specialist-os-hero-a.png',0,0,1280,720);
s.images.add({blob:new Uint8Array(await fs.readFile(path.join(root,'docs/assets/brand/specialist-os-logo-b-transparent.png'))),contentType:'image/png',alt:'Specialist OS Logo B',fit:'contain',crop:{left:0.18,top:0.245,right:0.17,bottom:0.215},position:{left:40,top:46,width:338,height:281}});
text(s,'LLM 也能做，\n为什么还要\n专业模型？',40,307,338,161,34,C.ink,true);
text(s,'用 Specialist OS\n让 Agent 按需调用\n本地专业能力',40,553,338,125,24,C.green);
note(s,'LLM 也能做，为什么还要专业模型？','用 Specialist OS 让 Agent 按需调用本地专业能力。通用模型已经可以看图、读文档、理解音频，也可以写代码或调用工具完成很多专业任务。今天讨论的是如何组织这项工作：什么时候直接用通用模型，什么时候让 Agent 调用一个专用实现。我们从任务需要交付的结果出发，看本地模型与算子怎样加入 Agent 的工作流。十五分钟分享之后，用十分钟看实际运行。工程同事可以沿用相同接口接入项目，产品同事可以把自己的业务材料带入这些路径。','用户确认的分享主题；README.md；skills/specialist-os/SKILL.md');

s=add('同一个目标，可以选择不同的执行路径');
text(s,'先确定下一步需要拿到什么',64,145,1140,66,33,C.green,true);
table(s,[['用户目标','交付到下一步','可调用的专业能力'],['编辑图片中的对象','像素级 mask','SAM 分割'],['把文档写入业务系统','文字区域与表格结构','PaddleOCR / MinerU'],['定位录音中的一次发言','文本与说话人时间线','Whisper / pyannote'],['继续编辑一段音乐','音符事件与 MIDI','Basic Pitch']],64,241,1152,335,[330,400,422],27);
text(s,'LLM 可以参与这些任务，Agent 按交付要求选择执行工具',64,616,1145,42,27,C.gray);
note(s,'不同执行路径','能理解一份材料，与怎样把结果交给下一个系统，是两个相连的设计问题。通用模型可以直接回答，也可以生成代码、组织工具调用。专用实现提供既定的输入输出：图像编辑需要 mask，文档入库需要区域和表格，录音检索需要时间线，编曲需要 MIDI。Agent 可以沿用这些实现，把结果拿回来继续推理与交互。这里没有把某类输出说成 LLM 永远做不到，而是展示可以复用的执行路径。','registry/models.yaml；本 deck 对应的视觉、文档、语音和音乐 CLI 证据');

s=add('Specialist OS：Agent 的专业能力层');
text(s,'Agent 组织任务，专业实现处理选中的步骤',64,145,1152,64,33,C.green,true);
for(const [i,label,body,result] of [
  [0,'LLM / Agent','理解用户目标\n选择执行路径','任务与输入文件'],
  [1,'Agent Skill','发现能力格式\n准备本机组件','适配任务的调用'],
  [2,'Runtime','策略路由与隔离\n加载和复用模型','执行与错误处理'],
  [3,'专业模型与算子','处理图片与声音\n执行专业计算','结果与产物来源'],
]){
  const x=64+i*294;
  text(s,String(i+1).padStart(2,'0'),x,248,248,86,61,C.green,true);
  text(s,label,x,362,264,55,30,C.ink,true);
  text(s,body,x,436,267,99,26,C.gray);
  text(s,result,x,563,269,46,25,C.green);
}
text(s,'CLI、Python SDK、HTTP、MCP 使用同一套能力契约',64,621,1140,42,27,C.gray);
note(s,'Agent 的专业能力层','LLM 理解目标，Agent 决定哪些步骤直接完成，哪些步骤交给工具。Specialist OS 把专业模型和确定性算子做成统一的能力接口，负责依赖准备、模型管理与隔离执行。结果回到 Agent 后，它可以解释结果、请求复核或继续下一步。宿主只要具备相应的 CLI 或 MCP 工具调用能力，就可以接入这条路径。Skill 是发现和调用说明，业务代码也可以直接使用 SDK 或 HTTP。','docs/architecture.md；specialist/runtime.py；specialist/providers/base.py；skills/specialist-os/references/integration.md');

s=add('按结果选择能力');
table(s,[['能力领域','参考模型与组件','输出'],['视觉感知','YOLO、SAM、Depth Anything','检测框、分割区域、相对深度'],['文档与界面','PaddleOCR、MinerU、OmniParser','文字、表格、界面元素'],['人体与身份','MediaPipe、InsightFace','关键点、姿态、相似度'],['视觉检索','OpenCLIP / SigLIP2','向量、相似结果'],['语音理解','whisper.cpp、Silero VAD、pyannote','转写、语音区间、说话人'],['音频处理与生成','DeepFilterNet、Fish Audio S2','降噪音频、合成与克隆音频'],['几何与媒体','OpenCV、FFmpeg','测量、变换、转码与剪辑']],64,171,1152,446,[233,515,404],24);
text(s,'Core 15 能力族，56 个 API；当前聚焦感知、媒体处理与专业计算',64,636,1120,36,23,C.gray);
note(s,'能力版图','Core 固定为 15 个能力族、56 个 API，包含算子和组合能力。选择时先问业务需要什么输出，再决定模型。ADR-003 保留深度估计、相机标定与 PnP 等已有算子，空间重建留在实验路线，生成式 3D 留在可选重型包路线。近期投入集中在安装、性能与调用质量。模型许可证和硬件要求按实际选中的提供方检查。Fish S2 使用独立本机服务。','specialist/core.py；registry/models.yaml；docs/adr/003-defer-spatial-3d-core.md');

s=add('图像编辑与复核：位置、区域和层次');
await img(s,'output/demo/slides/build/source-v3/ppt/media/image3.png',64,154,535,382);
await img(s,'output/demo/slides/build/source-v3/ppt/media/image4.png',649,154,535,382);
text(s,'目标检测',64,551,535,48,31,C.ink,true);
text(s,'目标位置可继续交给 SAM 做分割',64,603,540,39,25,C.gray);
text(s,'相对深度',649,551,535,48,31,C.ink,true);
text(s,'补充前后层次，用于区域排序',649,603,550,39,25,C.gray);
note(s,'视觉案例','两幅图来自本轮 CLI 结果。检测定位人和车辆，再将公交车框传给 SAM 提取整车区域。深度图补充前后层次，适合区域排序。业务可围绕目标建立复核或素材处理流程。深度属于相对估计，真实尺寸测量需要额外标定与尺度依据。现场会重新运行这条路径，展示原图与结果。','output/demo/core15-20260907/assets/vision-detect.json；vision-segment.json；vision-depth.json');

s=add('文档入库：保留文字位置与表格结构');
await img(s,'output/demo/slides/build/source-v3/ppt/media/image5.png',64,156,453,453);
const blocks=vision.find(r=>r.capability==='vision.ocr').result.blocks;
text(s,String(blocks.length),571,157,600,112,88,C.green,true);
text(s,'PaddleOCR 识别的文本区域',571,274,620,50,29,C.ink,true);
text(s,'Date & Day    Paper    Titles    Marks',571,342,620,65,25,C.gray);
text(s,'MinerU 保留更完整的文档结构',571,437,620,49,29,C.ink,true);
text(s,`${doc.result.pages} 页文档，${doc.result.tables.length} 张表格\n正文与公式用于检索和后续处理`,571,498,624,107,27,C.gray);
note(s,'文档案例',`左侧是本轮 PaddleOCR 返回的 ${blocks.length} 个文字区域，位置与置信度支持字段复核。MinerU 本轮处理了 ${doc.result.pages} 页论文，提取 ${doc.result.tables.length} 张表格，耗时 ${(doc.performance.latency_ms/1000).toFixed(1)} 秒。正文、公式和表格可以分别进入知识检索与数据校验流程。现场打开解析结果，选择一张表格与原文核对。工程接入时，字段质量应使用自己的业务样本评估。`,'output/demo/core15-20260907/assets/document-parse.json；output/demo/rehearsals/20260907T030519.523169Z/stdout.json');

s=add('界面操作：给 Agent 可定位的目标');
await img(s,'output/demo/slides/build/source-v3/ppt/media/image6.png',64,176,765,438);
text(s,String(screen.result.elements.length),874,177,320,102,80,C.green,true);
text(s,'解析元素',874,288,320,48,29,C.ink,true);
text(s,'文字与图标\n归一化坐标\n元素类型与置信度',874,366,337,166,27,C.gray);
text(s,'OmniParser 为后续操作提供目标信息，Agent 决定操作步骤',64,635,1130,39,25,C.gray);
note(s,'界面案例',`左侧展示本轮 OmniParser 标注结果，共 ${screen.result.elements.length} 个元素，包含文本、图标、坐标和置信度。独立 CPU 彩排约 24 秒。Agent 可以借此定位搜索栏或文件入口，再交给自动化工具操作并重新观察。产品机会包括界面知识提取和测试辅助。`,'output/demo/core15-20260907/assets/screen-parse.json；output/demo/rehearsals/20260907T030813.425434Z/summary.json');

s=add('空间产物：模型、表面与相机位姿');
await img(s,'output/demo/spatial-viewer/generation-1440.png',64,150,365,300);
await img(s,'output/demo/spatial-viewer/scene-1440.png',458,150,365,300);
await img(s,'output/demo/spatial-viewer/calibration-1440.png',852,150,365,300);
text(s,'图片生成 3D',64,470,365,40,28,C.ink,true);
text(s,'TripoSR · 10,019 顶点 · 38.09 秒',64,515,365,32,21,C.gray);
text(s,'单目场景几何',458,470,365,40,28,C.ink,true);
text(s,'MoGe 2 · 568,186 三角面 · 3.55 秒',458,515,365,32,21,C.gray);
text(s,'标定与 PnP',852,470,365,40,28,C.ink,true);
text(s,'11 张照片 · 0.248 / 0.193 px RMS',852,515,365,32,21,C.gray);
text(s,'三条路线都通过 Specialist CLI 产生真实产物；生成资产、估计几何与测量依据分开表达',64,604,1150,42,24,C.gray);
note(s,'空间能力','三类空间结果分别对应生成资产、估计几何和可测量的相机依据。它们都由本机 CLI 执行，输出保留输入、模型、设备、耗时和哈希。实验路线不改变 Core 15。','output/demo/spatial/triposr-chair-01/result.json；output/demo/spatial/moge2-bus-03/result.json；output/demo/spatial/chessboard-01/summary.json');

s=add('录音检索：找到谁在什么时候说了什么',true);
const diarize=audio.find(r=>r.capability==='speech.diarize').result;
text(s,'20 秒录音',64,167,440,66,45,C.lime,true);
text(s,`${diarize.speakers} 位说话人，${diarize.segments.length} 段发言`,64,251,550,55,32,C.white,true);
text(s,'“The customer reported an intermittent\ncheckout failure after the morning release.”',64,354,1150,113,34,C.white);
await player(s,'noisy','降噪前',64,518,520,true);
await player(s,'denoised','DeepFilterNet 降噪后',650,518,520,true);
note(s,'音频案例','这里用的是一段二十秒的故障讨论，内容涉及结账失败、支付回调和回滚。VAD 先给出语音区间，Whisper 提供转写，pyannote 将发言分成两位说话人的四个片段。DeepFilterNet 对带噪版本输出新的音频文件。这样的结果可以进入会议检索、客服回访或事件复盘。说话人标签是自动分组，不代表实名身份。现场会播放处理前后音频，并打开转写与时间线，不需要让听众阅读整个 JSON。','本次音频彩排 output/demo/rehearsals/20260907T020603.536311Z/stdout.json；输入 meeting-two-speaker.wav 与 noisy 版本');

s=add('音乐素材：节奏、调性与录音指纹');
text(s,'Vibe Ace',64,156,1152,66,42,C.green,true);
text(s,'Kevin MacLeod / 爵士乐 / 61.46 秒',64,232,1130,45,26,C.gray);
text(s,musicAnalysis.result.bpm.toFixed(1),64,324,380,112,84,C.green,true);
text(s,'BPM 估计',64,445,380,44,28,C.ink,true);
text(s,`${musicAnalysis.result.key} ${musicAnalysis.result.scale}`,477,341,700,86,57,C.ink,true);
text(s,'Essentia 调性分析',477,445,700,44,28,C.gray);
text(s,'素材库按节奏与调性筛选配乐，录音指纹支持同源素材核对',64,554,1152,56,29,C.ink);
text(s,'现场播放原曲，再查看分析和指纹比较结果',64,623,1152,35,23,C.gray);
note(s,'音乐素材',`Music 扩展包把音乐文件变成可查询的素材信息。这里使用 Kevin MacLeod 的 Vibe Ace，许可 CC BY 3.0。本机 Essentia 输出 BPM ${musicAnalysis.result.bpm.toFixed(2)} 和 ${musicAnalysis.result.key} ${musicAnalysis.result.scale}，这是模型估计，尚未用标注数据评估准确率。Chromaprint 对同一录音进行指纹比较，是同源素材核对的基础，不是音乐风格相似度。产品可先验证素材编目与剪辑选曲场景。所有数值来自同一输入的实际 CLI 结果。`,'output/music-rehearsal/manifest.json；00-music-analyze.json；03-music-compare_recording.json；https://freemusicarchive.org/music/Kevin_MacLeod/Jazz_Sampler/Vibe_Ace');

s=add('音乐制作：分轨试听与多乐器 MIDI');
text(s,String(musicTracks.result.tracks.reduce((sum,track)=>sum+track.notes.length,0)),64,151,410,120,90,C.green,true);
text(s,`${musicTracks.result.tracks.length} 个乐器轨道的音符事件`,64,286,425,47,29,C.ink,true);
text(s,'MuScriptor 保留乐器与时间\n完整和分轨 MIDI 继续编曲',64,365,425,106,27,C.gray);
text(s,`${(musicTracks.performance.latency_ms/1000).toFixed(2)} 秒`,64,522,400,60,42,C.green,true);
text(s,'本机 MPS，权重已准备',64,593,420,36,23,C.gray);
const histogram = s.charts.add('bar', {position:{left:505,top:211,width:710,height:366},categories:musicTracks.result.tracks.map(track=>track.instrument),series:[{name:'音符事件数',values:musicTracks.result.tracks.map(track=>track.notes.length),fill:C.green}],barOptions:{direction:'column',grouping:'clustered'},hasLegend:false,xAxis:{textStyle:{fontSize:20,fill:C.gray}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:20,fill:C.ink}}});
const { applyPresentationChartFont } = await import(path.join(skill,'container_tools/artifact_tool_utils.mjs'));
applyPresentationChartFont(histogram,{fontFamily:font});
text(s,'本次转写的乐器轨道',505,157,700,48,28,C.ink,true);
text(s,`人声与伴奏分离 ${(musicStems.performance.latency_ms/1000).toFixed(2)} 秒，现场试听 WAV`,505,605,710,45,25,C.gray);
note(s,'音乐转写',`同一段 Vibe Ace，Basic Pitch 返回 ${musicNotes.result.notes.length} 个音符，用于旋律草稿。MuScriptor 输出电贝斯、电钢琴、鼓三个轨道，共 1063 个音符，本机 MPS 用时 ${(musicTracks.performance.latency_ms/1000).toFixed(2)} 秒。图表直接统计本次各轨道的音符数量，页面提供完整和分轨 MIDI。audio-separator 用时 ${(musicStems.performance.latency_ms/1000).toFixed(2)} 秒，返回人声和伴奏 WAV。该曲是器乐录音，人声轨可检查串音，不能据此判断人声分离准确率。现场先听原曲，再检查轨道、下载 MIDI。MuScriptor 属实验能力，权重为非商业许可，MIDI 未作乐谱量化。应用场景包括编曲草稿、练习素材和素材整理。`, 'output/music-rehearsal/manifest.json；05-music-transcribe-multitrack.json；06-music-separate.json；https://huggingface.co/MuScriptor/muscriptor-medium');

s=add('音乐工作流：练习素材与原创配乐');
const singing = await read('output/music-workflow-rehearsal/music-parse_singing.json');
const fullMusic = await read('output/music-workflow-rehearsal/music-transcribe_full.json');
const generatedMusic = await read('output/music-generation-controls/music-generate.json');
for (const result of [singing, fullMusic, generatedMusic]) {
  if (result.error || result.performance.cached) throw new Error('Music workflow evidence is not valid');
}
text(s,"Let's Go Fishin' / Karissa Hobbs / 132.99 秒",64,146,1145,61,31,C.green,true);
table(s,[['用户目标','实际执行','交付结果'],['演唱练习','Whisper + ROSVOT + Essentia','歌词、旋律 MIDI、节拍'],['编曲草稿','MuScriptor + 分离 + 分轨转写','多轨 MIDI、人声与伴奏'],['创作配乐','ACE-Step 1.5 本机生成','15 秒爵士放克 WAV']],64,223,1152,244,[245,490,417],25);
for (const [index, [id, label]] of [['original','原曲'],['vocals','人声'],['instrumental','伴奏'],['generated','生成配乐']].entries()) {
  await player(s,id,label,64+index*294,498,260);
}
text(s,`唱段解析 ${(singing.performance.latency_ms/1000).toFixed(2)} s    完整转写 ${(fullMusic.performance.latency_ms/1000).toFixed(2)} s    配乐生成 ${(generatedMusic.performance.latency_ms/1000).toFixed(2)} s`,64,623,1152,40,24,C.gray);
note(s,'音乐组合与生成','用同一首带人声与伴奏的完整录音演示练习素材。唱段解析先转换音频格式，再调用 Whisper、ROSVOT 和 Essentia，将歌词片段与音符按时间重叠建立关联。完整转写保留 MuScriptor 乐器轨道，再分离音源，用 Basic Pitch 和 ROSVOT 细化相应音轨。各步骤的结果和来源都保留。ACE-Step 使用独立提示词与 Vibe Ace 参考音频生成十五秒配乐，固定种子 42，指定 100 BPM 与 C major。BPM 与调性是生成条件，输出是否精确遵循需要另行测量。本机模型已准备，所有结果关闭缓存。现场打开 music-singing 页面试听原曲、人声、伴奏和生成配乐，再下载 MIDI。','output/music-workflow-rehearsal/manifest.json；output/music-generation-controls/manifest.json；output/music-singing-rehearsal/manifest.json');

s=add('Agent Skill：按任务准备本机能力');
text(s,'01',64,170,104,70,48,C.green,true);text(s,'发现所需能力',190,172,1000,52,32,C.ink,true);
text(s,'先看简表，再读取选中能力的输入与输出格式',190,232,1000,48,27,C.gray);
text(s,'02',64,331,104,70,48,C.green,true);text(s,'按需下载与安装',190,333,1000,52,32,C.ink,true);
text(s,'在本机隔离环境中准备模型，后续任务复用',190,393,1000,48,27,C.gray);
text(s,'03',64,492,104,70,48,C.green,true);text(s,'执行并交付产物',190,494,1000,52,32,C.ink,true);
text(s,'向用户展示图片、音频或文本，保留结果来源',190,554,1000,48,27,C.gray);
note(s,'Agent Skill','Skill 的目标是让新用户只描述任务，不必先熟悉几十个模型。第一次调用先确认 CLI，再查紧凑能力列表，只为选中的能力读取完整格式。安装使用已经验证的 Python 3.12，模型与依赖按任务下载到本机。连续请求可以用批处理复用 worker，跨多轮 Agent 对话可以用持久 MCP 服务。第一次下载与框架初始化要单独展示进度。MinerU pipeline 和 Fish S2 这类额外模型服务需要明确准备，不能把环境未就绪说成已可运行。','skills/specialist-os/SKILL.md；specialist capabilities --compact；docs/deployment.md');

s=add('本地执行：模型准备一次，连续任务复用');
text(s,`${perf.speedup}×`,64,174,450,130,102,C.green,true);
text(s,'三次 YOLO 调用的批处理加速',64,318,1130,62,33,C.ink,true);
table(s,[['执行方式','总耗时','模型进程'],['三次独立 CLI',`${(perf.fresh_cli_ms.reduce((a,b)=>a+b,0)/1000).toFixed(2)} 秒`,'每次重新启动'],['同一批处理',`${(perf.batch_wall_ms/1000).toFixed(2)} 秒`,'连续调用复用']],64,399,1152,156,[550,260,342],27);
text(s,'能力发现输出减少 93%，按能力查详情可进一步缩小上下文',64,592,1150,42,26,C.gray);
text(s,'M4 Pro CPU，权重已下载，禁用结果缓存；不含首次安装',64,642,1130,31,21,C.gray);
note(s,'性能实测',`三次独立 YOLO CPU 调用合计 ${(perf.fresh_cli_ms.reduce((a,b)=>a+b,0)/1000).toFixed(2)} 秒，批处理共 ${(perf.batch_wall_ms/1000).toFixed(2)} 秒，加速 ${perf.speedup} 倍。权重已下载，结果缓存关闭，比较的是启动与执行开销。批处理中后两次推理为 ${perf.batch_inference[1].latency_ms} 和 ${perf.batch_inference[2].latency_ms} 毫秒。能力简表输出减少约 93%。本次独立视觉主线为 25.0 秒，音频主线为 18.9 秒。不同模型应分别测量。`,'scripts/benchmark_agent_path.py；output/demo/performance.json；output/demo/rehearsals/20260907T030519.523169Z/summary.json；output/demo/rehearsals/20260907T030746.572431Z/summary.json');

s=add('工程接入');
text(s,'先用 Agent 验证，再沿用到业务代码',64,145,1135,59,33,C.green,true);
text(s,'Python SDK',64,239,670,50,32,C.ink,true);
text(s,'runtime = SpecialistRuntime(\n    backend="real", isolate=True\n)\ntry:\n    result = runtime.run(\n        "vision.ocr", path\n    )\nfinally:\n    runtime.close()',64,306,725,306,26,C.ink);
table(s,[['接入方式','适合的使用场景'],['CLI','脚本与批处理'],['Python SDK','应用内部逻辑'],['MCP','持续 Agent 会话'],['HTTP','服务边界']],832,249,384,342,[145,239],23);
note(s,'工程接入','工程接入从一个能力开始。这里省略了 import 和安装步骤，代码表达的重点是显式使用 real backend、开启隔离并在结束时关闭 runtime。完整例子在 Skill 的 integration 参考文件里。短任务用 CLI 很直接，Python 项目可以持有 runtime，Agent 长会话适合 MCP，跨进程服务可以用 HTTP。业务代码还要处理 error、置信度和产物引用。服务部署时保持本地监听，需要跨机器时配置认证与明确的数据策略。','skills/specialist-os/references/integration.md；docs/deployment.md；specialist/runtime.py');

s=add('什么时候值得调用专业能力');
text(s,'按任务选择，沿用已经验证的实现',64,146,1147,66,33,C.green,true);
table(s,[['任务条件','选择依据','接入时验证'],['需要特定产物','mask、坐标、时间线、MIDI','下游能否直接消费'],['大量重复处理','固定流程、模型进程复用','总耗时与单件处理成本'],['希望本地运行','数据位置与可用硬件','内存、安装与许可证'],['需要开放理解','意图、上下文与例外情况','LLM 直接处理或组合工具']],64,250,1152,332,[246,430,476],26);
text(s,'在同一批业务样本上比较候选路径，再决定分工',64,619,1150,42,26,C.gray);
note(s,'什么时候值得调用','专业模型是 Agent 可以选择的工具。对特定产物和重复流程，可以复用一个验证过的专业实现。希望数据留在本机时，还需要结合硬件、首次安装和模型许可判断。对开放理解与例外处理，通用模型仍承担重要角色。最终用同一批业务材料比较候选路径，统计质量、端到端等待时间、资源消耗和人工复核量。前面的 YOLO 数据比较的是两种本地执行方式，没有进行专业模型与 LLM 的同题成本或质量对照，因此不能据此给出普遍优劣结论。','用户确认的主题与任务分工原则；output/demo/performance.json；registry/models.yaml');

s=add('10 分钟现场：Codex 调用 CLI 并交付结果',true);
text(s,'任务输入、真实执行、产物检查、打开交付页面',64,161,1130,70,36,C.white,true);
text(s,'00:00  发起音乐长任务，查看能力发现与视觉处理\n02:15  文档与界面理解\n03:45  语音转写与降噪对照\n05:15  歌曲练习工作区、多轨 MIDI 与生成配乐\n07:15  人体、检索与空间结果\n09:00  批处理性能与项目接入',64,268,1140,290,30,C.white);
text(s,'产品选一个场景，工程接一个能力',64,583,1140,61,40,C.lime,true);
note(s,'现场演示','现在切换到具备本地工具调用能力的 Agent。先从用户目标开始，让 Agent 查能力、执行任务，再展示可用结果。每个案例回答同一个问题：用户下一步拿这个产物做什么？视觉展示检测框、mask 和深度，文档展示表格和位置，语音展示播放定位，音乐展示音符与 MIDI。所有现场请求关闭结果缓存。某个任务超过预定时间，就转到独立步骤并保留当前运行状态。最后展示相同能力接口怎样接入现有项目。','docs/demo-runbook.zh-CN.md；scripts/rehearse_demo.py；scripts/rehearse_music.py');

if (p.slides.items.length!==17 || durations.reduce((a,b)=>a+b,0)!==900) throw new Error('Timing or slide count mismatch');
speaker[0]+='\n\nLogo：docs/assets/brand/specialist-os-logo-b-transparent.png，源自 Logo B';
p.slides.items[0].speakerNotes.textFrame.setText(speaker[0]);
await fs.mkdir(path.join(workspaceDir,'final'), {recursive:true});
await fs.writeFile(path.join(workspaceDir,'final/Specialist-OS-AHA-v5-Speaker-Notes.md'),`# LLM 也能做，为什么还要专业模型？\n\n用 Specialist OS 让 Agent 按需调用本地专业能力\n\n15 分钟分享，10 分钟现场演示\n\n第 9 和 12 页内嵌音频，放映时点击波形播放。\n\n${speaker.join('\n\n')}`);
const basePath=path.join(build,'layout.pptx');
const candidatePath=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(basePath);
execFileSync(runtimePython, [path.join(root,'scripts/embed_slide_audio.py'),basePath,candidatePath,path.join(workspaceDir,'build/media/manifest.json')], {stdio:'inherit'});
for(let i=0;i<p.slides.items.length;i++){
  const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const tableOwners=[2,4,12,14,15,16];
await finalizePresentation({workspaceDir,candidatePath,finalPath:path.join(workspaceDir,'final/Specialist-OS-AHA-v5.pptx'),pythonExecutable:runtimePython,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],explicitTotalSlideCount:17,requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:[11],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation-aha.json')});
