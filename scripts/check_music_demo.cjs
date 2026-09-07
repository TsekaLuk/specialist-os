/* Check the served Music evidence, including real audio and timeline pixels. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const output = path.resolve(process.argv[3] || 'output/music-browser');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [{width:1440,height:1000}, {width:390,height:844}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(process.argv[2] || 'http://127.0.0.1:8742/music/index.html');
      await page.waitForFunction(() => [...document.querySelectorAll('audio')].every(a => a.readyState >= 1 && a.duration > 0));
      const media = await page.evaluate(async () => {
        const result = [];
        for (const audio of document.querySelectorAll('audio')) {
          audio.muted = true;
          await audio.play();
          audio.pause();
          result.push({source: new URL(audio.currentSrc).pathname, duration: audio.duration});
        }
        return result;
      });
      assert.ok(media.length >= 3, 'source and separated stems must be playable');
      const canvases = await page.locator('canvas').evaluateAll(elements => elements.map(canvas => {
        const pixels = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
        let painted = 0;
        for(let i=3;i<pixels.length;i+=4) if(pixels[i]) painted++;
        return {painted, width:canvas.width, height:canvas.height};
      }));
      assert.ok(canvases.length >= 4, 'basic and multitrack timelines must render');
      assert.ok(canvases.every(canvas => canvas.painted > 100));
      const before = await page.locator('#roll').screenshot();
      await page.locator('#audio').evaluate(audio => {audio.currentTime = 10;});
      await page.waitForFunction(() => Math.abs(document.querySelector('#audio').currentTime - 10) < .1);
      await page.waitForTimeout(200);
      assert.ok(!before.equals(await page.locator('#roll').screenshot()), 'seek cursor must move');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false);
      for (const link of await page.locator('a[download]').all()) {
        const response = await page.request.get(new URL(await link.getAttribute('href'), page.url()).href);
        assert.equal(response.ok(), true);
      }
      await page.screenshot({path:path.join(output, `music-${viewport.width}.png`), fullPage:true});
      assert.deepEqual(errors, []);
      results.push({viewport, media, canvases, overflow});
      await page.close();
    }
    fs.writeFileSync(path.join(output,'browser-check.json'), JSON.stringify({passed:true,results},null,2));
    console.log(JSON.stringify({passed:true,viewports:results.length}));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
