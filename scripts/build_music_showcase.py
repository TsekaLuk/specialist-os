#!/usr/bin/env python3
"""Publish a listening page from validated, uncached local CLI Music evidence."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specialist.artifacts import ArtifactStore
from specialist.schemas import validate_envelope


def build(source: Path, output: Path, generation: Path | None = None, workflows: Path | None = None) -> None:
    manifest = json.loads((source / "manifest.json").read_text())
    fixture = manifest["fixture"]
    filename = fixture.get("filename", "vibe-ace.ogg")
    if Path(filename).name != filename:
        raise ValueError("Fixture filename must be local")
    audio = source / filename
    if hashlib.sha256(audio.read_bytes()).hexdigest() != fixture["sha256"]:
        raise ValueError("Music fixture hash mismatch")
    evidence = {}
    for record in manifest["records"]:
        filename = record["result"]
        if Path(filename).name != filename:
            raise ValueError("Evidence filename must be local")
        envelope = json.loads((source / filename).read_text())
        validate_envelope(envelope)
        command = record["command"]
        if not isinstance(command, list) or "--backend" not in command or command.index("--backend") + 1 >= len(command):
            raise ValueError("Evidence requires a complete CLI command")
        if (record["status"] != "ok" or envelope.get("error")
                or envelope["performance"]["cached"] is not False
                or envelope["input"]["sha256"] != fixture["sha256"]
                or envelope["capability"] != record["capability"]
                or "--isolate" not in command
                or "--backend" not in command
                or command[command.index("--backend") + 1] != "real"):
            raise ValueError(f"Unverified Music evidence: {filename}")
        evidence.setdefault(record["capability"], envelope)
    analysis = evidence["music.analyze"]
    notes = evidence["music.transcribe_notes"]
    midi_uri = notes["result"]["midi"]
    store = ArtifactStore(Path(manifest.get("artifact_home", source / "home")) / "artifacts")
    midi = store.resolve(midi_uri)
    if hashlib.sha256(midi.read_bytes()).hexdigest() != midi_uri.removeprefix("artifact://"):
        raise ValueError("MIDI artifact hash mismatch")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(audio, output / "source.ogg")
    shutil.copyfile(midi, output / "transcription.mid")

    def export_artifact(uri, name):
        artifact = store.resolve(uri)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != uri.removeprefix("artifact://"):
            raise ValueError("Music artifact hash mismatch")
        shutil.copyfile(artifact, output / name)

    extra_sections = ""
    if generation:
        generated = json.loads((generation / "music-generate.json").read_text())
        validate_envelope(generated)
        metadata = json.loads((generation / "manifest.json").read_text())
        if generated["error"] or generated["performance"]["cached"] or generated["capability"] != "music.generate":
            raise ValueError("Generation evidence must be successful and uncached")
        command = metadata["command"]
        if "--isolate" not in command or command[command.index("--backend") + 1] != "real":
            raise ValueError("Generation must use the real isolated CLI")
        from specialist.registry import get_spec
        prompt_path = Path(command[command.index(get_spec("music.generate").command) + 1])
        if hashlib.sha256(prompt_path.read_bytes()).hexdigest() != generated["input"]["sha256"]:
            raise ValueError("Generation prompt must match the executed input")
        generated_store = ArtifactStore(Path(metadata["artifact_home"]) / "artifacts")
        uri = generated["result"]["audio"]
        file = generated_store.resolve(uri)
        if hashlib.sha256(file.read_bytes()).hexdigest() != uri.removeprefix("artifact://"):
            raise ValueError("Generation artifact hash mismatch")
        shutil.copyfile(file, output / "generated.wav")
        shutil.copyfile(generation / "music-generate.json", output / "music-generate.json")
        prompt = html.escape(generated["result"]["prompt"])
        extra_sections += f'<section><h2>原创配乐</h2><p>{prompt}</p><audio controls preload="metadata" aria-label="ACE-Step 原创配乐"><source src="generated.wav" type="audio/wav"></audio><p><a href="generated.wav" download>下载配乐 WAV</a> · <a href="music-generate.json">生成记录</a></p></section>'
    if workflows:
        workflow_manifest = json.loads((workflows / "manifest.json").read_text())
        workflow_html = ""
        for record in workflow_manifest["records"]:
            if Path(record["result"]).name != record["result"]:
                raise ValueError("Workflow evidence filename must be local")
            value = json.loads((workflows / record["result"]).read_text())
            validate_envelope(value)
            if record["status"] != "ok" or value["error"] or value["result"]["status"] != "ok" or value["performance"]["cached"]:
                raise ValueError("Workflow evidence must be successful and uncached")
            if value["input"]["sha256"] != fixture["sha256"]:
                raise ValueError("Workflow input must match the recording")
            command = record["command"]
            if (value["capability"] != record["capability"] or "--isolate" not in command
                    or command[command.index("--backend") + 1] != "real"):
                raise ValueError("Workflow must use its real isolated CLI capability")
            shutil.copyfile(workflows / record["result"], output / record["result"])
            label = {"music.parse_singing": "歌词与演唱旋律", "music.transcribe_full": "完整转写与分轨细化"}[record["capability"]]
            children = value["result"]["children"]
            summary = " · ".join(html.escape(name) for name in children)
            transcript = children.get("audio.transcribe", {}).get("result", {}).get("text", "")
            workflow_html += f'<h3>{label}</h3><p>{summary}</p><p>{html.escape(transcript)}</p><a href="{html.escape(record["result"], quote=True)}">查看组合结果</a>'
        extra_sections += f'<section><h2>组合工作流</h2>{workflow_html}</section>'
    vocal = evidence.get("music.transcribe_vocal", {}).get("result")
    display_tracks = []
    if vocal:
        export_artifact(vocal["midi"], "vocal.mid")
        display_tracks.append({"instrument": "Vocal melody", "notes": vocal["notes"]})
        extra_sections += '<section><div class="music-chart-heading"><h2>人声旋律转写</h2><a href="vocal.mid" download>下载人声 MIDI</a></div><div class="music-track"><canvas data-track="0" width="1200" height="240" role="img" aria-label="ROSVOT 人声旋律音符时间线"></canvas></div></section>'
    multitrack = evidence.get("music.transcribe_multitrack", {}).get("result")
    if multitrack:
        export_artifact(multitrack["midi"], "multitrack.mid")
        tracks_html = ""
        for index, track in enumerate(multitrack["tracks"]):
            export_artifact(track["midi"], f"track-{index}.mid")
            instrument = html.escape(track["instrument"])
            display_index = len(display_tracks)
            display_tracks.append(track)
            tracks_html += f'<div class="music-track"><div class="music-chart-heading"><h3>{instrument}</h3><a href="track-{index}.mid" download>{len(track["notes"])} 音符 · MIDI</a></div><canvas data-track="{display_index}" width="1200" height="240" role="img" aria-label="{instrument} 音符时间线"></canvas></div>'
        extra_sections += f'<section><div class="music-chart-heading"><h2>多乐器转写</h2><a href="multitrack.mid" download>下载完整多轨 MIDI</a></div>{tracks_html}</section>'
    separation = evidence.get("music.separate", {}).get("result")
    if separation:
        players = ""
        for stem, uri in separation["stems"].items():
            export_artifact(uri, f"stem-{stem}.wav")
            label = {"vocals": "人声", "instrumental": "伴奏"}.get(stem, stem)
            players += f'<div><h3>{html.escape(label)}</h3><audio controls preload="metadata" aria-label="{html.escape(label)}分轨"><source src="stem-{stem}.wav" type="audio/wav"></audio><a href="stem-{stem}.wav" download>下载 WAV</a></div>'
        extra_sections += f'<section><h2>音源分离</h2><div class="music-stems">{players}</div></section>'
    for record in manifest["records"]:
        shutil.copyfile(source / record["result"], output / record["result"])
    shutil.copyfile(source / "manifest.json", output / "manifest.json")
    for name in ("tokens.css", "music-evidence.css"):
        shutil.copyfile(ROOT / "design-system" / name, output / name)
    shutil.copyfile(ROOT / "docs/assets/brand/specialist-os-logo-b-transparent.png", output / "logo.png")
    dataset = json.dumps({"analysis": analysis["result"], "notes": notes["result"]["notes"], "tracks": display_tracks}, allow_nan=False).replace("<", "\\u003c")
    rows = "".join(f'<tr><th scope="row">{html.escape(capability)}</th><td>{html.escape(item["provider"])}</td><td>{item["performance"]["latency_ms"] / 1000:.2f} s</td></tr>' for capability, item in evidence.items())
    links = "".join(f'<li><a href="{html.escape(record["result"], quote=True)}">{html.escape(record["result"])}</a></li>' for record in manifest["records"])
    title = html.escape(fixture["title"])
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Specialist OS Music</title><link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="music-evidence.css">
<header><img src="logo.png" alt="Specialist OS"><strong>Specialist OS</strong><span>Music Intelligence</span><a href="../core15-20260907/index.html">全部能力</a></header>
<main><section class="music-heading"><div><p class="muted">音乐分析与转写</p><h1>{title}</h1><p>{html.escape(fixture["author"])} / {html.escape(fixture.get("category", "Music"))} / {html.escape(fixture["license"])}</p></div><a class="download" href="transcription.mid" download>下载 MIDI</a></section>
<section class="music-player"><h2>原始录音</h2><audio id="audio" controls preload="metadata" aria-label="{title} 原始录音"><source src="source.ogg" type="audio/ogg"></audio><p id="media-error" role="alert" hidden>无法播放音频。<a href="source.ogg" download>下载原始录音</a></p></section>
<dl class="music-metrics"><div><dt>BPM 估计</dt><dd>{analysis["result"]["bpm"]:.1f}</dd></div><div><dt>调性估计</dt><dd>{html.escape(analysis["result"]["key"])} {html.escape(analysis["result"]["scale"])}</dd></div><div><dt>音符事件</dt><dd>{len(notes["result"]["notes"])}</dd></div><div><dt>录音时长</dt><dd>{analysis["result"]["duration"]:.2f} s</dd></div></dl>
<section><div class="music-chart-heading"><h2>音符时间线</h2><span class="muted">Basic Pitch / MIDI pitch</span></div><canvas id="roll" width="1200" height="360" role="img" aria-label="本次转写的音高与时间分布"></canvas><p class="muted">横轴：秒　纵轴：MIDI 音高</p></section>
<section class="music-evidence"><div><h2>本机 CLI 运行记录</h2><table><thead><tr><th>能力</th><th>Provider</th><th>推理耗时</th></tr></thead><tbody>{rows}</tbody></table><p class="muted">权重已准备，关闭结果缓存。调性和音符来自模型估计。</p></div><div><h2>结果文件</h2><ul>{links}<li><a href="manifest.json">命令与输入来源</a></li></ul></div></section>
{extra_sections}
<footer><a href="{html.escape(fixture["source"], quote=True)}">{title}</a> by {html.escape(fixture["author"])} · <a href="{html.escape(fixture["license_url"], quote=True)}">{html.escape(fixture["license"])}</a><p class="hash">SHA256 {fixture["sha256"]}</p></footer></main>
<script id="music-data" type="application/json">{dataset}</script><script src="music-evidence.js"></script></html>'''
    (output / "index.html").write_text(page, encoding="utf-8")
    shutil.copyfile(ROOT / "design-system/music-evidence.js", output / "music-evidence.js")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "output/music-rehearsal")
    parser.add_argument("--output", type=Path, default=ROOT / "output/demo/music")
    parser.add_argument("--generation", type=Path)
    parser.add_argument("--workflows", type=Path)
    args = parser.parse_args()
    build(args.source, args.output, args.generation, args.workflows)
    print(args.output / "index.html")
