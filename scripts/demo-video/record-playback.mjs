import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
const file=path.resolve(process.argv[2]);
const manifest=JSON.parse(await fs.readFile(file,'utf8'));
const root=path.resolve(import.meta.dirname,'../..');
const audio=[];
const browser=await chromium.launch({headless:true});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try {
  const prepare=await browser.newPage();
  await prepare.goto('http://127.0.0.1:8744/music-singing/index.html');
  await prepare.waitForLoadState('networkidle');
  await prepare.evaluate(()=>{
    document.querySelectorAll('script').forEach(el=>el.remove());
    const heading=document.querySelector('.music-heading');
    heading.querySelector('a').remove();
    const source=document.querySelector('#audio').closest('section');
    const stems=[...document.querySelectorAll('section')].find(el=>el.querySelector('.music-stems'));
    document.querySelector('main').replaceChildren(heading,source,stems);
    for(const el of document.querySelectorAll('link[href]')) el.href=el.href;
    for(const el of document.querySelectorAll('img[src]')) el.src=el.src;
    source.querySelector('source').src='/recorded-music/source.ogg';
    source.querySelector('a').href='/recorded-music/source.ogg';
    for(const [index,name] of ['vocals','instrumental'].entries()) {
      stems.querySelectorAll('source')[index].src='/recorded-music/'+name+'.wav';
      stems.querySelectorAll('a')[index].href='/recorded-music/'+name+'.wav';
    }
  });
  await fs.writeFile(path.join(root,'output/demo/recorded-music/index.html'),await prepare.content());
  await prepare.close();
  for(const id of ['04-audio-results','06-music-results']) {
    const context=await browser.newContext({viewport:{width:1600,height:900},recordVideo:{dir:manifest.output,size:{width:1600,height:900}}});
    const page=await context.newPage();
    const started=Date.now();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const video=page.video();
    if(id==='04-audio-results') {
      await page.goto('http://127.0.0.1:8744/live-workspace/index.html#audio.transcribe');
      await page.waitForLoadState('networkidle');
      await page.locator('.result-panel').scrollIntoViewIfNeeded();
      await delay(5000);
      await page.goto('http://127.0.0.1:8744/live-workspace/index.html#audio.denoise');
    } else await page.goto('http://127.0.0.1:8744/recorded-music/index.html');
    await page.waitForLoadState('networkidle');
    const players=await page.locator('audio').all();
    assert.equal(players.length,id==='04-audio-results'?2:3);
    for(const player of players) {
      await player.scrollIntoViewIfNeeded();
      await player.evaluate(async el=>{el.currentTime=el.duration>100?30:0;await el.play();});
      const at=(Date.now()-started)/1000;
      const state=await player.evaluate(el=>({source:el.currentSrc,start:el.currentTime}));
      const mediaPath=path.join(root,'output/demo',new URL(state.source).pathname);
      await fs.access(mediaPath);
      audio.push({clip:id,at,sourceStart:state.start,duration:8,file:mediaPath});
      await delay(8000);
      await player.evaluate(el=>el.pause());
    }
    await page.screenshot({path:path.join(manifest.output,id+'.png')});
    assert.deepEqual(errors,[]);
    await context.close();
    const dest=path.join(manifest.output,id+'-synced.webm');
    await video.saveAs(dest);await video.delete();
    manifest.clips.find(clip=>clip.id===id).file=dest;
  }
  manifest.audio=audio;
  await fs.writeFile(file,JSON.stringify(manifest,null,2));
  console.log(JSON.stringify({players:audio.length,manifest:file}));
} finally {await browser.close();}
