import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(import.meta.dirname, '../..');
const output = path.join(root, 'output/demo/recordings', new Date().toISOString().replace(/[:.]/g, '-'));
await fs.mkdir(output, {recursive: true});
const py = path.join(root, '.venv/bin/python');
const browser = await chromium.launch({headless: true});
const clips = [];
const evidence = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const quote = s => /^[a-zA-Z0-9_./:-]+$/.test(s) ? s : `'${s.replaceAll("'", "'\\''")}'`;
let active;
async function command(argv, onOutput = () => {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0], argv.slice(1), {cwd: root, detached: true, env: {...process.env, PYTHONUNBUFFERED: '1'}});
    active = child;
    let stdout = '', stderr = '';
    const timeout = setTimeout(() => {try {process.kill(-child.pid, 'SIGKILL');} catch {}}, 600000);
    child.stdout.on('data', data => {stdout += data; onOutput(String(data));});
    child.stderr.on('data', data => {stderr += data; onOutput(String(data));});
    child.on('error', error => {clearTimeout(timeout); active = null; reject(error);});
    child.on('close', code => {
      clearTimeout(timeout); active = null;
      if (code !== 0) reject(new Error(`Exit ${code}: ${stderr || stdout}`));
      else resolve(stdout);
    });
  });
}
async function recording(id, title, work) {
  const context = await browser.newContext({viewport: {width: 1600, height: 900}, recordVideo: {dir: output, size: {width: 1600, height: 900}}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const video = page.video();
  try {
    await work(page);
    await page.screenshot({path: path.join(output, `${id}.png`)});
    assert.deepEqual(errors, []);
  } finally {await context.close();}
  const destination = path.join(output, `${id}.webm`);
  await video.saveAs(destination);
  await video.delete();
  clips.push({id, title, file: destination});
  console.log(`Recorded ${id}`);
}
async function consolePage(page) {
  await page.setContent(`<!doctype html><html><head><style>
    *{box-sizing:border-box}body{margin:0;background:#171d1b;color:#eaf1ee;font:24px/1.5 Menlo,monospace;padding:38px 48px}
    header{font:22px system-ui;color:#bed600;border-bottom:1px solid #3c4c43;padding-bottom:20px;margin-bottom:24px}
    #clock{float:right;color:#a7b9af}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:inherit}
  </style></head><body><header>Specialist OS / CLI execution <span id="clock">0.0 s</span></header><pre id="log"></pre></body></html>`);
  await page.evaluate(() => {const start = performance.now(); setInterval(() => {document.querySelector('#clock').textContent = ((performance.now()-start)/1000).toFixed(1)+' s';},100);});
}
async function step(page, id, python, verb, source, options, home) {
  const dir = path.join(output, id);
  const cli = [python, '-m', 'specialist', ...(home ? ['--home', home] : []), '--backend', 'real', '--isolate', verb, source, '--json', '--options', JSON.stringify({...options, no_cache: true})];
  // The browser receives actual subprocess output. It never replays invented typing.
  const argv = [py, 'scripts/capture_demo_step.py', '--output', dir, '--', ...cli];
  await page.locator('#log').evaluate((el, text) => {el.textContent = '$ '+text+'\n\n';}, argv.map(quote).join(' '));
  const events = [{at: 0, type: 'command', argv}];
  const started = performance.now();
  let pending = Promise.resolve();
  await command(argv, data => {
    events.push({at: (performance.now()-started)/1000, type: 'output', data});
    pending = pending.then(() => page.locator('#log').evaluate((el, text) => {el.textContent += text; window.scrollTo(0,document.body.scrollHeight);},data));
  });
  await pending;
  await fs.writeFile(path.join(dir, 'events.json'), JSON.stringify(events, null, 2));
  const result = JSON.parse(await fs.readFile(path.join(dir, 'result.json'), 'utf8'));
  assert.equal(result.error, null);
  assert.equal(result.performance.cached, false);
  assert.notEqual(result.result.status, 'degraded');
  evidence.push({id, path: path.join(dir, 'result.json'), capability: result.capability, performance: result.performance});
  await delay(2500);
  return result;
}
async function publish(ids) {
  await command(['uv','run','--no-project','--with','pillow','--python',py,'python','scripts/publish_live_recording.py',...ids.flatMap(id => ['--result',path.join(output,id,'result.json')])]);
}
async function workspace(page, capability) {
  await page.goto(`http://127.0.0.1:8744/live-workspace/index.html#${capability}`);
  await page.waitForLoadState('networkidle');
  await delay(1800);
}
try {
  await recording('01-vision-cli', 'CLI / Object detection, segmentation and depth', async page => {
    await consolePage(page);
    const source = 'docs/assets/e2e/bus-input.jpg';
    const detection = await step(page,'detect',py,'detect',source,{device:'cpu'});
    const bus = detection.result.items.find(item => item.label === 'bus');
    assert.ok(bus, 'The detector must supply the SAM prompt');
    await step(page,'segment',py,'segment',source,{bbox:bus.bbox});
    await step(page,'depth',py,'depth',source,{});
  });
  await publish(['detect','segment','depth']);
  await recording('02-vision-results', 'Workspace / Inspect the delivered visual results', async page => {
    for (const capability of ['vision.detect','vision.segment','vision.depth']) {
      await workspace(page,capability);
      const img = page.locator('main img').last();
      if(await img.count()) await img.scrollIntoViewIfNeeded();
      await delay(4500);
    }
  });
  await recording('03-audio-cli', 'CLI / Transcription and noise reduction', async page => {
    await consolePage(page);
    await step(page,'transcribe',py,'transcribe','docs/assets/e2e/meeting-two-speaker.wav',{});
    await step(page,'denoise',py,'denoise','docs/assets/e2e/meeting-two-speaker-noisy.wav',{strength:'balanced'});
  });
  await publish(['transcribe','denoise']);
  await recording('04-audio-results','Workspace / Review the transcript and audio',async page => {
    await workspace(page,'audio.transcribe');
    await delay(5000);
    await workspace(page,'audio.denoise');
    const audio = page.locator('audio').last();
    await audio.scrollIntoViewIfNeeded();
    await audio.evaluate(async el => {await el.play();});
    await delay(8000);
    await audio.evaluate(el => el.pause());
  });
  await recording('05-music-cli','CLI / Separate vocals and accompaniment',async page => {
    await consolePage(page);
    await step(page,'separate',path.join(root,'output/music-research/separator-env/bin/python'),'music-separate','output/music-singing-rehearsal/singing.ogg',{local_only:true},'output/music-rehearsal/home');
  });
  const musicSite = path.join(root,'output/demo/recorded-music');
  await fs.mkdir(musicSite,{recursive:true});
  const separation = JSON.parse(await fs.readFile(path.join(output,'separate/result.json'),'utf8'));
  const musicAssets = [];
  for (const ref of separation.artifacts) {
    const sha = ref.sha256;
    const source = path.join(root,'output/music-rehearsal/home/artifacts',sha.slice(0,2),sha.slice(2,4),sha);
    const name = ref.metadata.stem + '.wav';
    await fs.copyFile(source,path.join(musicSite,name));
    musicAssets.push({name,sha256:sha});
  }
  await fs.copyFile(path.join(root,'output/music-singing-rehearsal/singing.ogg'),path.join(musicSite,'source.ogg'));
  // Reuse the existing music workspace styling and real HTML audio controls.
  await recording('06-music-results','Workspace / Original, vocals and accompaniment',async page => {
    await page.goto('http://127.0.0.1:8744/music-singing/index.html');
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => {
      const original = document.querySelector('#audio').closest('section');
      const stems = [...document.querySelectorAll('section')].find(el=>el.querySelector('.music-stems'));
      const main = document.querySelector('main');
      if(!main || !original || !stems) throw new Error('Music workspace changed');
      main.replaceChildren(original,stems);
      original.querySelector('source').src='/recorded-music/source.ogg';
      stems.querySelectorAll('source')[0].src='/recorded-music/vocals.wav';
      stems.querySelectorAll('source')[1].src='/recorded-music/instrumental.wav';
      for(const audio of main.querySelectorAll('audio')) audio.load();
    });
    const playback = [];
    for(const selector of ['#audio','audio[aria-label="人声分轨"]','audio[aria-label="伴奏分轨"]']) {
      const audio = page.locator(selector);
      await audio.scrollIntoViewIfNeeded();
      await audio.evaluate(async el=>{el.currentTime=30;await el.play();});
      playback.push({selector,source:await audio.evaluate(el=>el.currentSrc),sourceStart:30});
      await delay(8000);
      await audio.evaluate(el=>el.pause());
    }
    await fs.writeFile(path.join(output,'music-playback.json'),JSON.stringify(playback,null,2));
  });
  await fs.writeFile(path.join(output,'manifest.json'),JSON.stringify({output, clips, evidence, musicAssets, speed:1, captured_at:new Date().toISOString()},null,2));
  console.log(JSON.stringify({output,clips:clips.length,evidence:evidence.length}));
} finally {
  if(active) {try {process.kill(-active.pid,'SIGKILL');} catch {}}
  await browser.close();
}
