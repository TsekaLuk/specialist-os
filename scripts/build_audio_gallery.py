"""Build the public audio gallery from saved CLI results."""

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(root=ROOT):
    assets = root / "docs/assets/e2e"
    manifest = json.loads((assets / "capability-gallery.json").read_text())
    cards = []
    for capability, filename in manifest["audio"].items():
        record = manifest["records"][capability]
        if record["status"] != "ok":
            continue
        for name in (filename, record["json"]):
            if Path(name).name != name or not (assets / name).is_file():
                raise ValueError(f"Missing gallery asset: {name}")
        envelope = json.loads((assets / record["json"]).read_text())
        if envelope.get("error") or envelope.get("result", {}).get("status") == "degraded":
            raise ValueError(f"Unsuccessful gallery result: {capability}")
        mime = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}[Path(filename).suffix]
        title = html.escape(capability)
        source = html.escape(filename, quote=True)
        provenance = html.escape(str(record["provider"]) + " / " + str(record["model"]))
        comparison = ''
        if capability == "audio.denoise":
            comparison = '<p>Before / 处理前</p><audio controls preload="metadata" aria-label="Noisy source"><source src="../assets/e2e/meeting-two-speaker-noisy.wav" type="audio/wav"></audio><p>After / 处理后</p>'
        cards.append(f'<section id="{title}"><h2>{title}</h2><p class="provider">{provenance}</p>{comparison}<audio controls preload="metadata" aria-label="{title}"><source src="../assets/e2e/{source}" type="{mime}"></audio><p class="links"><a href="../assets/e2e/{source}">Audio / 音频</a><a href="../assets/e2e/{html.escape(record["json"], quote=True)}">Result JSON</a></p></section>')
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Specialist OS · Audio Gallery</title>
<style>
*{box-sizing:border-box;letter-spacing:0}body{margin:0;background:#fff;color:#292f33;font:16px/1.5 system-ui,sans-serif}header,main,footer{max-width:1200px;margin:auto;padding:28px}header{display:flex;align-items:center;gap:20px;border-bottom:1px solid #ddd}header img{width:64px;height:64px;object-fit:contain}h1{font-size:28px;margin:0}header p{margin:4px 0;color:#555}a{color:#28624a;text-underline-offset:3px}header>a{margin-left:auto}h2{font-size:18px;overflow-wrap:anywhere;margin:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}section{border:1px solid #d8ddd7;border-top:4px solid #bfda00;border-radius:4px;padding:20px;min-width:0;scroll-margin:20px}section:target{outline:2px solid #28624a}.provider{font-size:13px;color:#626862;overflow-wrap:anywhere;min-height:40px}audio{width:100%;height:54px}.links{display:flex;gap:20px;font-size:13px}footer{border-top:1px solid #ddd;font-size:14px}@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.grid{grid-template-columns:1fr}header{flex-wrap:wrap}header>a{margin-left:0}header,main,footer{padding:20px}h1{font-size:24px}}
</style><header><img src="../assets/brand/specialist-os-logo-b.png" alt=""><div><h1>Specialist OS</h1><p>Audio gallery / 音频展厅</p></div><a href="https://github.com/TsekaLuk/specialist-os">GitHub</a></header><main><div class="grid">''' + "\n".join(cards) + '''</div></main><footer><a href="../assets/e2e/capability-gallery.png">Capability gallery / 全部能力</a> · <a href="https://github.com/TsekaLuk/specialist-os/blob/main/docs/assets/e2e/README.md">Sources / 素材来源</a></footer></html>
'''


def build():
    path = ROOT / "docs/audio/index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if (ROOT / "docs/audio/index.html").read_text() != render():
            raise SystemExit("Audio gallery is stale; run scripts/build_audio_gallery.py")
    else:
        build()
