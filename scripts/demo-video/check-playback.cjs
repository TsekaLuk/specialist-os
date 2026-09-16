const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const checks=[];
  try {
    for(const width of [1440,390]) {
      const page=await browser.newPage({viewport:{width,height:900}});
      await page.goto('http://127.0.0.1:8744/video/index.html');
      const video=page.locator('video');
      await video.evaluate(async el=>{el.muted=true;await el.play();});
      await page.waitForFunction(()=>document.querySelector('video').currentTime>0.3);
      const metrics=await video.evaluate(el=>({duration:el.duration,width:el.videoWidth,height:el.videoHeight,error:el.error}));
      assert.ok(metrics.duration>138 && metrics.duration<140);
      assert.equal(metrics.width,1920);assert.equal(metrics.error,null);
      for(const time of [5,25,45,60,90,125]) {
        await video.evaluate((el,t)=>new Promise(resolve=>{el.pause();el.addEventListener('seeked',resolve,{once:true});el.currentTime=t;}),time);
        const colors=await video.evaluate(el=>{
          const c=document.createElement('canvas');c.width=160;c.height=90;
          const ctx=c.getContext('2d');ctx.drawImage(el,0,0,160,90);
          const pixels=ctx.getImageData(0,0,160,90).data;const levels=new Set();
          for(let i=0;i<pixels.length;i+=4)levels.add(pixels[i]);return levels.size;
        });
        assert.ok(colors>30,'Video frame is nonblank');
      }
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:`output/demo/video/playback-${width}.png`});
      checks.push({viewportWidth:width,...metrics});await page.close();
    }
    fs.writeFileSync('output/demo/video/playback-check.json',JSON.stringify({passed:true,checks},null,2));
    console.log(JSON.stringify({passed:true,checks}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
