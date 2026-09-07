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
      await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
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
      assert.equal(await page.locator('select, textarea').count(), 0, 'recorded runs must not expose inactive settings');
      const copy = page.getByRole('button', {name:'Copy CLI command'});
      if (await copy.isEnabled()) {
        const expected = await page.getByLabel('CLI command', {exact:true}).textContent();
        await copy.click();
        await page.getByRole('button', {name:'Copied',exact:true}).waitFor();
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), expected);
      }
      const input = page.getByRole('searchbox', {name:'Filter capabilities'});
      const before = await input.evaluate(el => getComputedStyle(el).boxShadow);
      await input.focus();
      await page.waitForTimeout(200);
      const after = await input.evaluate(el => getComputedStyle(el).boxShadow);
      assert.notEqual(before, after, 'search focus must be visible');
      await page.evaluate(() => { location.hash = 'vision.detect'; });
      await page.getByRole('heading', {name:'vision.detect',exact:true}).waitFor();
      await page.waitForFunction(() => {
        const image = document.querySelector('img.preview');
        return image?.complete && image.naturalWidth > 0;
      });
      const badge = await page.getByLabel('Run status: ok').evaluate(el => {
        const rect = el.getBoundingClientRect();
        const icon = el.querySelector('svg').getBoundingClientRect();
        const label = el.querySelector('span').getBoundingClientRect();
        return {display:getComputedStyle(el).display,height:rect.height,width:rect.width,
          aligned:Math.abs(icon.y + icon.height / 2 - label.y - label.height / 2) < 2};
      });
      assert.ok(['flex', 'inline-flex'].includes(badge.display));
      assert.equal(badge.height, 24);
      assert.ok(badge.width > badge.height && badge.aligned, 'status badge must remain one horizontal row');
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
