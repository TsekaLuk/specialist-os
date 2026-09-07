/* Verify the published application, including responsive layout and media. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const output = path.resolve('output/workspace-browser');
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true});
  const results = [];
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({viewport:{width,height:900}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto((process.argv[2] || 'http://127.0.0.1:8742/core15-20260907/index.html') + '#speech.synthesize');
      await page.getByRole('heading', {name:'speech.synthesize',exact:true}).waitFor();
      await page.waitForFunction(() => document.querySelector('audio')?.readyState >= 1);
      const media = await page.locator('audio').evaluate(async audio => {
        audio.muted = true;
        await audio.play();
        audio.pause();
        return {duration:audio.duration,source:audio.currentSrc};
      });
      assert.ok(media.duration > 0);
      const input = page.getByRole('textbox', {name:'Filter capabilities'});
      const before = await input.evaluate(el => getComputedStyle(el.parentElement).boxShadow);
      await input.focus();
      const after = await input.evaluate(el => getComputedStyle(el.parentElement).boxShadow);
      assert.notEqual(before, after, 'search focus must be visible');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({path:path.join(output,`workspace-${width}.png`),fullPage:true});
      assert.deepEqual(errors, []);
      results.push({width,media,focus:true,overflow:false});
      await page.close();
    }
    fs.writeFileSync(path.join(output,'check.json'), JSON.stringify({passed:true,results},null,2));
    console.log(JSON.stringify({passed:true,results}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
