const {chromium}=require('playwright');
const path=require('path');
const fs=require('fs');
(async()=>{
const root=__dirname;const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:960},deviceScaleFactor:2});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('file://'+path.join(root,'index.html'));await page.evaluate(()=>document.fonts.ready);
await page.mouse.move(0,0);await page.screenshot({animations:'disabled',path:path.join(root,'01-overview-dark.png')});
await page.locator('nav [data-view=sync]').click();await page.mouse.move(0,0);await page.screenshot({animations:'disabled',path:path.join(root,'02-sync-dark.png')});
await page.locator('#raw').click();if(!await page.locator('#messages pre').count())throw new Error('Raw view did not open');await page.locator('#dialogue').click();
await page.locator('#time').selectOption('7');if(await page.locator('#old-count').textContent()!=='2')throw new Error('Time filtering incorrect');
await page.locator('#time').selectOption('all');if(await page.locator('#old-count').textContent()!=='0')throw new Error('All dates incorrect');
await page.locator('#time').selectOption('30');await page.locator('#project').selectOption('模型测试');if(await page.locator('.session-row').count()!==2)throw new Error('Project filtering incorrect');
await page.locator('#search').fill('不存在的示例会话');if(!await page.locator('.empty').count())throw new Error('Empty state missing');
await page.locator('#search').fill('');await page.locator('#project').selectOption('全部项目');await page.locator('[data-category=protected]').click();if(!await page.locator('#edit').isHidden())throw new Error('Local title not protected');
await page.locator('[data-category=new]').click();await page.locator('#edit').click();await page.locator('#title-input').fill('示例标题编辑校验');await page.locator('#edit-form button').click();if(await page.locator('#preview-name').textContent()!=='示例标题编辑校验')throw new Error('Title editing failed');
await page.locator('#import').click();if(!await page.locator('#toast').isVisible())throw new Error('Import boundary missing');
const overflow=[];for(const width of [1440,1120,920,740,390]){await page.setViewportSize({width,height:960});for(const view of ['overview','sync','backups','settings']){await page.evaluate(v=>showView(v),view);const check=await page.evaluate(()=>({page:document.documentElement.scrollWidth>innerWidth+1,main:document.querySelector('main').scrollWidth>document.querySelector('main').clientWidth+1}));if(check.page||check.main)overflow.push({width,view,...check})}}
await page.setViewportSize({width:1440,height:960});await page.reload();await page.evaluate(()=>showView('overview'));await page.locator('#theme').click();await page.mouse.move(0,0);await page.screenshot({animations:'disabled',path:path.join(root,'03-overview-light.png')});
await page.setViewportSize({width:920,height:760});await page.evaluate(()=>showView('sync'));await page.screenshot({animations:'disabled',path:path.join(root,'check-920.png')});
fs.writeFileSync(path.join(root,'verification.json'),JSON.stringify({pageErrors:errors,horizontalOverflow:overflow,verified:['navigation','time filtering','project filtering','search and empty state','protected local titles','dialogue and raw modes','new title editing','non-operational import feedback','light and dark themes'],viewports:[1440,1120,920,740,390]},null,2));
await browser.close();console.log(JSON.stringify({errors,overflow}));if(errors.length||overflow.length)process.exitCode=1;
})();
