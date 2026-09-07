/* Real browser checks against the generated GLB viewer. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const output = path.resolve(process.argv[3] || 'output/demo/spatial-viewer');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [{width:1440,height:900}, {width:390,height:844}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(process.argv[2] || 'http://127.0.0.1:8742/spatial-viewer/site/');
      for (const id of ['generation', 'scene', 'calibration']) {
        await page.selectOption('#view', id);
        await page.waitForFunction(id => window.demoReady === id, id);
        await page.waitForTimeout(300);
        const before = await page.locator('canvas').screenshot();
        const pixels = await page.evaluate(() => {
          const canvas = document.querySelector('canvas');
          const copy = document.createElement('canvas');
          copy.width = canvas.width; copy.height = canvas.height;
          const ctx = copy.getContext('2d'); ctx.drawImage(canvas, 0, 0);
          const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
          let visible = 0;
          for (let i = 0; i < data.length; i += 4) {
            if (Math.abs(data[i] - 241) + Math.abs(data[i+1] - 243) + Math.abs(data[i+2] - 242) > 30) visible++;
          }
          return {visible, total: copy.width * copy.height, overflow: document.documentElement.scrollWidth > innerWidth};
        });
        assert.ok(pixels.visible > 300, `${id}: blank canvas`);
        assert.equal(pixels.overflow, false);
        await page.click('#zoom-in');
        await page.waitForTimeout(300);
        assert.ok(!before.equals(await page.locator('canvas').screenshot()), `${id}: zoom unchanged`);
        await page.click('#reset');
        const box = await page.locator('canvas').boundingBox();
        await page.mouse.move(box.x + box.width*.5, box.y + box.height*.55);
        await page.mouse.down();
        await page.mouse.move(box.x + box.width*.7, box.y + box.height*.6, {steps:12});
        await page.mouse.up();
        await page.waitForTimeout(500);
        assert.ok(!before.equals(await page.locator('canvas').screenshot()), `${id}: rotation unchanged`);
        await page.check('#rotate');
        const rotation = await page.locator('canvas').screenshot();
        await page.waitForTimeout(400);
        assert.ok(!rotation.equals(await page.locator('canvas').screenshot()), `${id}: auto rotation unchanged`);
        await page.uncheck('#rotate');
        if (id !== 'calibration') {
          const surface = await page.locator('canvas').screenshot();
          await page.check('#wire');
          await page.waitForTimeout(300);
          assert.ok(!surface.equals(await page.locator('canvas').screenshot()), `${id}: wireframe unchanged`);
          await page.uncheck('#wire');
        }
        await page.click('#reset');
        await page.waitForTimeout(400);
        await page.screenshot({path:path.join(output, `${id}-${viewport.width}.png`), fullPage:true});
        results.push({id, viewport, ...pixels});
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
    fs.writeFileSync(path.join(output, 'browser-check.json'), JSON.stringify({passed:true, results}, null, 2));
    console.log(JSON.stringify({passed:true, cases:results.length}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
