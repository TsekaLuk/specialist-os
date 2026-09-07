"""Export a local, playable Core 15 demo from successful CLI gallery evidence."""

import argparse
import html
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specialist.artifacts import ArtifactError, ArtifactStore
from specialist.core import CORE_FAMILIES
from specialist.registry import get_spec


FAMILY_NAMES = {
    "detection": "目标检测", "segmentation": "图像分割", "ocr": "文字识别",
    "depth": "相对深度", "screen": "界面理解", "document": "文档解析",
    "speech_recognition": "语音识别", "diarization": "说话人与时间线", "denoise": "音频降噪",
    "speech_generation": "语音生成", "human_landmarks": "人体关键点", "visual_search": "视觉检索",
    "face_identity": "人脸核验", "geometry": "确定性几何与图像处理", "media": "媒体处理",
}


def replay_command(envelope):
    """Reconstruct file-input CLI arguments from retained routing evidence."""
    source = (envelope.get("input") or {}).get("path")
    if not source or envelope.get("capability") == "speech.clone_voice":
        return None
    path = Path(source)
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != envelope["input"].get("sha256"):
        return None
    routing = next((step for step in envelope.get("trace", []) if step.get("stage") == "routing"), {})
    requested = routing.get("requested", {})
    if requested.get("capability") != envelope["capability"] or not isinstance(requested.get("options"), dict):
        return None
    return ["specialist", "--backend", "real", "--isolate", get_spec(envelope["capability"]).command,
        str(path), "--json", "--options", json.dumps(requested["options"])]


def successful(envelope, *, allow_cached=False):
    return (
        bool(envelope.get("provider"))
        and isinstance(envelope.get("result"), dict)
        and not envelope.get("error")
        and envelope["result"].get("status") != "degraded"
        and (allow_cached or (envelope.get("performance") or {}).get("cached") is False)
        and not any("fallback" in str(warning).lower() for warning in envelope.get("warnings", []))
    )


def render(assets: Path, home: Path, *, allow_cached=False):
    from generate_readme_gallery import _annotated_image, _slug

    manifest = json.loads((assets / "capability-gallery.json").read_text())
    stamp = manifest.get("updated_at") or manifest["generated_at"]
    if manifest.get("backend") != "real":
        raise ValueError("Demo export requires real provider evidence")
    store = ArtifactStore(home / "artifacts")
    media_dir = assets / "previews"
    media_dir.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "docs/assets/brand/specialist-os-logo-b-transparent.png", assets / "logo.png")
    cards, export = [], []
    missing_previews = set()

    def copy_uri(uri, name, suffix):
        destination = media_dir / f"{_slug(name)}{suffix}"
        try:
            source = store.resolve(uri)
        except ArtifactError:
            if not allow_cached:
                raise
            digest = uri.removeprefix("artifact://")
            source = next((path for path in assets.rglob("*") if path.is_file()
                and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest), None)
            if source is None:
                missing_previews.add(name)
                return None
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        return destination.relative_to(assets).as_posix()

    def image_tag(filename, alt):
        return f'<a class="visual" href="assets/{html.escape(filename, quote=True)}" target="_blank"><img loading="lazy" src="assets/{html.escape(filename, quote=True)}" alt="{html.escape(alt, quote=True)}"></a>'

    def audio_tag(filename, label):
        return f'<p class="media-label">{html.escape(label)}</p><audio controls preload="metadata" aria-label="{html.escape(label, quote=True)}" src="assets/{html.escape(filename, quote=True)}"></audio>'

    for family, names in CORE_FAMILIES.items():
        for name in names:
            record = manifest["records"].get(name)
            if record is None:
                raise ValueError(f"No execution record for {name}")
            envelope = json.loads((assets / record["json"]).read_text())
            passed = record["status"] == "ok" and successful(envelope, allow_cached=allow_cached)
            payload = envelope.get("result") or {}
            preview = ""
            preview_path = None
            source_name = Path(str((envelope.get("input") or {}).get("path") or "")).name
            source = assets / source_name
            if passed:
                overlay = {
                    "vision.detect": ("bus-input.jpg", "detect"),
                    "vision.segment": ("bus-input.jpg", "sam"),
                    "vision.ocr": ("ocr-table.png", "ocr"),
                    "human.pose": ("hand-input.jpg", "pose"),
                    "human.hand_landmarks": ("hand-input.jpg", "hands"),
                    "human.face_landmarks": ("person-input.jpg", "face"),
                }.get(name)
                if overlay:
                    destination = media_dir / f"{_slug(name)}.png"
                    _annotated_image(assets / overlay[0], payload, overlay[1]).save(destination)
                    preview_path = destination.relative_to(assets).as_posix()
                elif name == "identity.face.detect":
                    destination = media_dir / f"{_slug(name)}.png"
                    _annotated_image(assets / "person-input.jpg", {"items": [{**face, "label": "face"} for face in payload.get("faces", [])]}, "detect").save(destination)
                    preview_path = destination.relative_to(assets).as_posix()
                else:
                    uri = payload.get("preview") or payload.get("image") or payload.get("image_path")
                    if isinstance(uri, str) and uri.startswith("artifact://"):
                        preview_path = copy_uri(uri, name, ".png")
                    elif (assets / f"{_slug(name)}-preview.png").is_file():
                        preview_path = f"{_slug(name)}-preview.png"
                    elif name == "document.parse":
                        table_image = next((Path(table["image"]).name for table in payload.get("tables", []) if table.get("image")), None)
                        candidate = next((a for a in envelope.get("artifacts", []) if a.get("metadata", {}).get("source_name") == table_image), None)
                        if candidate:
                            suffix = ".jpg" if candidate["mime"] == "image/jpeg" else ".png"
                            preview_path = copy_uri(candidate["uri"], name, suffix)
                if preview_path:
                    preview += image_tag(preview_path, name)
                ranked = payload.get("results") if family == "visual_search" else None
                if ranked:
                    preview += '<ol class="ranked">'
                    for result in ranked:
                        filename = Path(result["reference"]).name
                        if (assets / filename).is_file():
                            preview += f'<li><img src="assets/{html.escape(filename)}" alt="{html.escape(filename)}"><span>{html.escape(filename)}<strong>{float(result["score"]):.4f}</strong></span></li>'
                    preview += '</ol>'
                audio = manifest.get("audio", {}).get(name)
                if name == "audio.denoise":
                    preview += audio_tag("meeting-two-speaker-noisy.wav", "处理前")
                if audio:
                    preview += audio_tag(audio, "处理后" if name == "audio.denoise" else name)
                elif family in {"speech_recognition", "diarization"}:
                    preview += audio_tag("meeting-two-speaker.wav", "原始录音")
                if name == "media.transcribe_video":
                    preview += '<video controls preload="metadata" src="assets/video-input.mp4"></video>'
                text = payload.get("text") or payload.get("markdown")
                if text:
                    preview += f'<p class="transcript">{html.escape(str(text)[:1200])}</p>'
                if payload.get("segments"):
                    preview += '<div class="timeline">'
                    for segment in payload["segments"][:12]:
                        preview += f'<p><time>{float(segment.get("start", 0)):.1f}–{float(segment.get("end", 0)):.1f}s</time> <b>{html.escape(str(segment.get("speaker") or "语音"))}</b> {html.escape(str(segment.get("text") or ""))}</p>'
                    preview += '</div>'
                if not preview:
                    scalars = {k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool)) and not str(v).startswith("artifact://")}
                    preview = f'<pre class="result">{html.escape(json.dumps(scalars or payload, ensure_ascii=False, indent=2)[:1800])}</pre>'
            else:
                error = envelope.get("error") or {"code": "degraded", "message": "子能力未就绪"}
                preview = f'<div class="unavailable"><strong>{html.escape(str(error.get("code")))}</strong><p>{html.escape(str(error.get("message"))[:400])}</p></div>'
            latency = (envelope.get("performance") or {}).get("latency_ms")
            seconds = f"{latency / 1000:.2f} s" if isinstance(latency, (int, float)) else ""
            status = "ok" if passed else "error"
            heading = html.escape(name)
            cards.append(f'''<article data-family="{family}" data-status="{status}" id="{name}">
<header><span>{FAMILY_NAMES[family]}</span><span class="status {status}">{"已完成" if passed else "待准备"}</span></header>
<h2><a class="workspace-link" href="workspace.html#{html.escape(name, quote=True)}">{heading}</a></h2><p class="provider">{html.escape(str(record.get("provider") or ""))} · {html.escape(str(record.get("model") or ""))}</p>
{preview}<footer><span>{seconds}</span><a href="assets/{html.escape(record["json"])}" target="_blank">结果 JSON</a></footer>
<details><summary>执行证据</summary><pre>{html.escape(json.dumps({"input_sha256":record.get("input_sha256"),"performance":envelope.get("performance"),"command":record.get("command")}, ensure_ascii=False, indent=2))}</pre></details></article>''')
            command = record.get("command") or replay_command(envelope)
            export.append({"capability": name, "family": family, "status": status, "preview": preview_path, "preview_unavailable": name in missing_previews, "json": record["json"], "latency_ms": latency, "cached": bool((envelope.get("performance") or {}).get("cached")), "command": command, "command_origin": "recorded" if record.get("command") else "reconstructed" if command else None})
    passed = sum(item["status"] == "ok" for item in export)
    options = ''.join(f'<option value="{key}">{value}</option>' for key, value in FAMILY_NAMES.items())
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Specialist OS · Core 15</title><style>
*{box-sizing:border-box;letter-spacing:0}body{margin:0;background:#f3f5f4;color:#2b3034;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:#28624a;text-underline-offset:3px}button,select{font:inherit}body>header{background:#fff;border-bottom:1px solid #d4dcd7}.heading{max-width:1600px;margin:auto;display:flex;align-items:center;gap:24px;padding:22px 32px}.logo{width:92px;height:76px;object-fit:cover;object-position:center}.heading h1{margin:0;font-size:32px}.heading p{margin:2px 0;color:#626a65}.counts{margin-left:auto;display:flex;gap:28px}.counts b{display:block;font-size:26px;color:#28624a}.counts span{font-size:12px;color:#626a65}.toolbar{max-width:1600px;margin:0 auto;display:flex;align-items:center;gap:16px;padding:22px 32px}.toolbar select{background:white;border:1px solid #b4c0b8;padding:8px;max-width:270px}.toolbar label{font-size:13px}.modes{display:flex;border-bottom:1px solid #aebbb1}.modes button{border:0;background:none;padding:8px 16px;cursor:pointer;color:#626a65}.modes button[aria-pressed=true]{box-shadow:inset 0 -3px #bed600;color:#2b3034;font-weight:600}.stamp{margin-left:auto;font-size:12px;color:#626a65}main{max-width:1600px;margin:auto;padding:0 32px 48px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;align-items:start}article{background:#fff;border:1px solid #d5ded8;border-radius:6px;overflow:hidden;min-width:0}article>header{padding:15px 18px 0;display:flex;gap:12px;justify-content:space-between;color:#657369;font-size:12px}h2{font-size:17px;margin:8px 18px 2px;overflow-wrap:anywhere}.provider{margin:0 18px 14px;color:#67716b;font-size:12px;overflow-wrap:anywhere;min-height:36px}.ok{color:#28624a}.error{color:#a44639}.visual{display:block;background:#edf1ef}.visual img{display:block;width:100%;height:228px;object-fit:contain}.media-label{font-size:12px;color:#626a65;margin:12px 18px 2px}audio{width:calc(100% - 28px);margin:0 14px;height:48px}video{width:100%;max-height:230px}.transcript{max-height:180px;overflow:auto;margin:16px 18px;font-size:13px;white-space:pre-wrap}.timeline{max-height:250px;overflow:auto;padding:0 18px;font-size:12px}.timeline p{border-left:3px solid #bed600;padding-left:9px}.timeline time{color:#28624a}.result{margin:0;padding:18px;max-height:228px;overflow:auto;background:#f0f4f1;font-size:13px}.unavailable{padding:24px 18px;background:#faf0ee;min-height:150px;font-size:13px;overflow-wrap:anywhere}.ranked{list-style:decimal;padding:0 18px 0 36px}.ranked li{padding:8px 0;font-size:12px}.ranked img{width:90px;height:66px;object-fit:contain;vertical-align:middle;margin-right:8px}.ranked span{display:inline-block;max-width:150px;overflow-wrap:anywhere;vertical-align:middle}.ranked strong{display:block;color:#28624a}article>footer{display:flex;justify-content:space-between;padding:14px 18px;font-size:12px;border-top:1px solid #e5eae6}details{padding:0 18px 15px;color:#657369;font-size:12px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}article[hidden]{display:none}.empty{display:none}body>footer{max-width:1600px;margin:auto;padding:0 32px 30px;color:#657369;font-size:12px}@media(max-width:1200px){main{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:900px){main{grid-template-columns:repeat(2,minmax(0,1fr))}.counts{gap:14px}.heading h1{font-size:26px}.toolbar{flex-wrap:wrap}.stamp{margin-left:0}}@media(max-width:600px){main{grid-template-columns:1fr;padding:0 16px 32px}.heading{padding:16px;flex-wrap:wrap;gap:14px}.counts{width:100%;margin-left:0;justify-content:space-between}.toolbar{padding:16px}.heading h1{font-size:24px}.visual img{height:260px}}
</style><header><div class="heading"><img class="logo" src="assets/logo.png" alt="Specialist OS"><div><h1>Specialist OS</h1><p>机器感知 · 媒体处理 · 专业计算</p></div><a class="workspace-nav" href="workspace.html">打开能力 Workspace</a><div class="counts"><div><b>15</b><span>能力族</span></div><div><b>56</b><span>Core API</span></div><div><b>__PASSED__</b><span>本轮完成</span></div><div><b>__PENDING__</b><span>待准备</span></div></div></div></header>
<nav class="toolbar"><label>能力族 <select id="family"><option value="all">全部能力</option>__OPTIONS__</select></label><div class="modes"><button data-mode="all" aria-pressed="true">全部</button><button data-mode="ok" aria-pressed="false">已完成</button><button data-mode="error" aria-pressed="false">待准备</button></div><span class="stamp">__STAMP__</span></nav><main>__CARDS__</main><footer>Core 15 · 本机 CLI 执行记录 · <a href="assets/capability-gallery.json">完整清单</a></footer>
<script>let mode='all';const family=document.querySelector('#family');function filter(){for(const card of document.querySelectorAll('article'))card.hidden=!((family.value==='all'||card.dataset.family===family.value)&&(mode==='all'||card.dataset.status===mode));}family.addEventListener('change',filter);for(const button of document.querySelectorAll('[data-mode]'))button.addEventListener('click',()=>{mode=button.dataset.mode;document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));filter();});</script></html>'''
    document = document.replace('__PASSED__', str(passed)).replace('__PENDING__', str(len(export) - passed)).replace('__OPTIONS__', options).replace('__STAMP__', html.escape(stamp)).replace('__CARDS__', '\n'.join(cards))
    (assets.parent / "index.html").write_text(document, encoding="utf-8")
    workspace = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Specialist OS · Capability Workspace</title><style>
*{box-sizing:border-box;letter-spacing:0}body{margin:0;background:#eef2f0;color:#2b3034;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,select{font:inherit}a{color:#28624a}.top{height:72px;padding:0 28px;background:#fff;border-bottom:1px solid #d6ded9;display:flex;align-items:center;gap:14px}.top img{width:45px;height:45px;object-fit:contain}.top h1{font-size:20px;margin:0}.top a{margin-left:auto}.layout{height:calc(100dvh - 72px);display:grid;grid-template-columns:270px minmax(0,1fr) 320px}.rail{background:#fff;border-right:1px solid #d6ded9;overflow:auto;padding:18px 12px}.rail h2{font-size:12px;color:#69756e;text-transform:uppercase;margin:10px 12px}.rail button{display:block;width:100%;border:0;background:transparent;text-align:left;padding:10px 12px;border-radius:4px;cursor:pointer;color:#34413a}.rail button:hover,.rail button[aria-current=true]{background:#e7efbd;color:#1f3e30}.rail small{display:block;color:#7b867f;font-size:11px}.center{min-width:0;overflow:auto;padding:28px 34px 50px}.eyebrow{font-size:12px;color:#69756e;text-transform:uppercase}.center h2{font-size:30px;margin:4px 0}.center .desc{color:#627069;margin:0 0 24px}.drop{border:1px dashed #aebcb4;background:#f8faf9;min-height:150px;display:grid;place-items:center;text-align:center;padding:24px;margin-bottom:20px}.result{background:#fff;border:1px solid #d6ded9;min-height:260px;padding:20px;overflow:auto}.result img{display:block;max-width:100%;max-height:420px;margin:auto;object-fit:contain}.result audio{width:100%;margin-top:10px}.result pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.empty{color:#7a857f}.side{background:#fff;border-left:1px solid #d6ded9;padding:24px;overflow:auto}.side h3{font-size:14px;margin:0 0 14px}.field{border-top:1px solid #e4e9e6;padding:14px 0}.field label{display:block;color:#69756e;font-size:12px;margin-bottom:5px}.field input,.field textarea,.field select{width:100%;border:1px solid #bcc8c0;padding:8px;background:#fff}.run{width:100%;border:0;background:#28624a;color:#fff;padding:11px;cursor:pointer}.run:hover{background:#1e4e3a}.statusline{display:flex;justify-content:space-between;color:#65736b;font-size:12px;margin:12px 0}.statusline b{color:#28624a}.evidence{font-size:12px;word-break:break-word}.evidence pre{max-height:260px;overflow:auto;background:#f0f4f1;padding:12px}@media(max-width:900px){.layout{height:auto;grid-template-columns:1fr}.rail{border-right:0;border-bottom:1px solid #d6ded9;max-height:230px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.rail h2{grid-column:1/-1}.side{border-left:0;border-top:1px solid #d6ded9}.center{padding:22px 16px}.top{padding:0 16px}}
</style><link rel="stylesheet" href="design-system.css"><body class="workspace"><header class="topbar"><img src="assets/logo.png" alt="Specialist OS"><h1>Capability Workspace</h1><a href="index.html">返回能力画廊</a></header><main class="app-shell"><nav class="capability-nav" id="rail"></nav><section class="workspace-main"><div class="eyebrow" id="family"></div><h2 id="title"></h2><p class="description" id="desc"></p><div class="input-zone"><div><strong>输入资产</strong><p id="input">选择本地文件后运行真实 Specialist CLI</p></div><input id="file" type="file"></div><div class="result-surface" id="result"></div></section><aside class="inspector"><h3>运行设置</h3><div class="field"><label>后端</label><select id="backend"><option>real</option></select></div><div class="field"><label>参数 JSON</label><textarea id="options" rows="6">{"no_cache":true}</textarea></div><button class="primary-action" id="run">复制 CLI 命令</button><div class="status-row"><span>状态</span><b id="status">已加载证据</b></div><div class="field evidence"><label>执行证据</label><pre id="evidence"></pre></div></aside></main><script type="module">
const data=await (await fetch('demo.json')).json(), cards=data.results, byId=new Map(cards.map(x=>[x.capability,x])); const rail=document.querySelector('#rail');
const families=[...new Set(cards.map(x=>x.family))]; for(const family of families){const h=document.createElement('h2');h.textContent=family;rail.append(h);for(const item of cards.filter(x=>x.family===family)){const b=document.createElement('button');b.dataset.id=item.capability;b.innerHTML=item.capability+'<small>'+item.status+'</small>';b.onclick=()=>select(item.capability);rail.append(b)}}
async function select(id){const item=byId.get(id);if(!item)return;document.querySelectorAll('.rail button').forEach(b=>b.setAttribute('aria-current',String(b.dataset.id===id)));document.querySelector('#family').textContent=item.family;document.querySelector('#title').textContent=item.capability;document.querySelector('#desc').textContent=item.status==='ok'?'本机真实 CLI 结果，可复核并下载证据':'该能力尚未完成本轮执行';document.querySelector('#status').textContent=item.status==='ok'?'已加载证据':'待准备';document.querySelector('#evidence').textContent=JSON.stringify(item,null,2);const result=document.querySelector('#result');result.innerHTML='';if(item.preview){const img=document.createElement('img');img.src='assets/'+item.preview;img.alt=item.capability;result.append(img)}const response=await fetch('assets/'+item.json);if(response.ok){const pre=document.createElement('pre');pre.textContent=JSON.stringify(await response.json(),null,2);result.append(pre)}else if(item.status!=='ok'){result.innerHTML='<p class="empty">保留真实错误状态。请先安装该能力所需的本地模型与依赖。</p>'}location.hash=id}
document.querySelector('#run').onclick=()=>{const item=byId.get(location.hash.slice(1)||cards[0].capability);const command=(item.command||[]).join(' ');navigator.clipboard?.writeText(command);document.querySelector('#status').textContent='CLI 命令已复制，可在本机运行并重新生成证据';};select(location.hash.slice(1)||cards[0].capability);
</script></html>'''
    (assets.parent / "workspace.html").write_text(workspace, encoding="utf-8")
    tokens_css = (ROOT / "design-system/tokens.css").read_text(encoding="utf-8")
    workspace_css = (ROOT / "design-system/workspace.css").read_text(encoding="utf-8").replace('@import url("tokens.css");', "")
    (assets.parent / "design-system.css").write_text(tokens_css + "\n" + workspace_css, encoding="utf-8")
    report = {"generated_at": stamp, "passed": passed, "total": len(export), "results": export}
    (assets.parent / "demo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--home", type=Path, default=Path.home() / ".specialist")
    parser.add_argument("--allow-cached", action="store_true", help="Display recorded cached outputs, retaining their cached flag; does not count as a fresh rehearsal")
    args = parser.parse_args()
    report = render(args.assets.resolve(), args.home.resolve(), allow_cached=args.allow_cached)
    print(json.dumps({"passed": report["passed"], "total": report["total"], "page": str(args.assets.resolve().parent / "index.html")}))
