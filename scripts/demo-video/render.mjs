import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';

const input = path.resolve(process.argv[2]);
const manifest = JSON.parse(await fs.readFile(input,'utf8'));
const output = path.dirname(input);
const publicDir = path.join(output,'render-assets');
await fs.mkdir(publicDir,{recursive:true});
const labels = [
  ['识别、分割与深度','Agent 将 YOLO 返回的检测框传给 SAM，生成可继续处理的视觉结果'],
  ['查看视觉结果','检查同一张输入的目标框、对象轮廓和相对深度图'],
  ['转写与降噪','调用 Whisper 与 DeepFilterNet，交付文本和处理后的录音'],
  ['查看语音结果','转写文本保留时间段，音频结果可直接试听和下载'],
  ['音乐分轨','对完整歌曲执行本地推理，生成独立的人声和伴奏'],
  ['试听分轨结果','依次对比原曲、人声和伴奏的同一段录音'],
];
let start = 0;
const clips = [];
for(const [index,clip] of manifest.clips.entries()) {
  const probe = JSON.parse(execFileSync('ffprobe',['-v','error','-show_format','-of','json',clip.file],{encoding:'utf8'}));
  const frames = Math.floor(Number(probe.format.duration)*30);
  const src = clip.id+'.webm';
  await fs.copyFile(clip.file,path.join(publicDir,src));
  clips.push({...clip,src,frames,start,title:labels[index][0],caption:labels[index][1]});
  start += frames;
}
const audio = [];
if(manifest.audio) {
  for(const item of manifest.audio) {
    const clip = clips.find(clip=>clip.id===item.clip);
    const src = path.basename(item.file);
    await fs.copyFile(item.file,path.join(publicDir,src));
    audio.push({src,start:clip.start+Math.round(item.at*30),frames:Math.round(item.duration*30),sourceStart:Math.round(item.sourceStart*30)});
  }
}
const props = {clips,audio,totalFrames:start};
await fs.writeFile(path.join(output,'edit.json'),JSON.stringify(props,null,2));
const serveUrl = await bundle({entryPoint:path.join(import.meta.dirname,'composition.jsx'),publicDir});
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE;
const composition = await selectComposition({serveUrl,id:'SpecialistDemo',inputProps:props,browserExecutable,logLevel:'info'});
let last = -1;
await renderMedia({serveUrl,composition,inputProps:props,browserExecutable,codec:'h264',crf:20,pixelFormat:'yuv420p',outputLocation:path.join(output,'Specialist-OS-E2E.mp4'),concurrency:3,
  onProgress:({progress})=>{const percent=Math.floor(progress*10)*10;if(percent!==last){last=percent;console.log(`Render ${percent}%`);}}});
console.log(path.join(output,'Specialist-OS-E2E.mp4'));
