import {test,expect} from '@playwright/test';
test('登录、浏览、筛选、收藏编辑、来源管理和退出',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.goto('/');await page.screenshot({path:'../tests/screenshots/01-login.png',fullPage:true});
 await page.getByLabel('云端地址').fill('http://127.0.0.1:18765');await page.getByLabel('登录密码').fill('local-test-password');await page.getByRole('button',{name:'连接我的图库'}).click();
 await expect(page.locator('.tile')).toHaveCount(6);await expect(page.locator('.tile img')).toHaveCount(6);await page.screenshot({path:'../tests/screenshots/02-gallery.png',fullPage:true});
 await page.locator('.tile').first().click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByLabel('收藏，长期保留').check();await page.getByLabel('标签',{exact:true}).fill('壁纸，山色');await page.getByLabel('备注',{exact:true}).fill('喜欢这幅风景');
 const dialog=page.getByRole('dialog');
 const original=dialog.locator('.viewer img');
 await expect(original).toBeVisible();
 const originalUrl=await original.getAttribute('src');
 const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/images');
 await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
 await refreshed;
 await expect(dialog).toBeVisible();
 await expect(original).toHaveAttribute('src',originalUrl!);
 await expect(dialog.getByLabel('备注',{exact:true})).toHaveValue('喜欢这幅风景');
 await expect(dialog.getByLabel('标签',{exact:true})).toHaveValue('壁纸，山色');
 await expect(dialog.getByLabel('收藏，长期保留')).toBeChecked();
 await page.getByRole('button',{name:'保存整理'}).click();await expect(page.getByRole('status')).toContainText('已保存');await page.screenshot({path:'../tests/screenshots/03-detail.png',fullPage:true});
 await page.getByRole('button',{name:'返回图库'}).click();await page.getByLabel('搜索图片').fill('风景');await expect(page.locator('.tile')).toHaveCount(1);await page.locator('.tile').click();await expect(page.getByLabel('备注',{exact:true})).toHaveValue('喜欢这幅风景');await page.getByRole('button',{name:'返回图库'}).click();
 await page.getByRole('button',{name:'⊞ 来源'}).click();await page.getByLabel('QQ 群号').fill('789');await page.getByLabel('来源名称').fill('新的测试群');await page.getByRole('button',{name:'添加来源',exact:true}).click();const card=page.locator('.source-card').filter({hasText:'新的测试群'});await expect(card).toBeVisible();await card.getByRole('button',{name:'暂停'}).click();await expect(card).toContainText('已暂停');await page.screenshot({path:'../tests/screenshots/04-sources.png',fullPage:true});
 await page.getByRole('button',{name:'⚙ 设置'}).click();await expect(page.getByRole('heading',{name:'设置与存储'})).toBeVisible();await page.screenshot({path:'../tests/screenshots/05-settings.png',fullPage:true});
 await page.getByRole('button',{name:'▧ 图库'}).click();await page.setViewportSize({width:1100,height:850});await page.getByRole('button',{name:'重置',exact:true}).click();await expect(page.locator('.tile')).toHaveCount(6);await expect(page.locator('.tile img')).toHaveCount(6);await page.screenshot({path:'../tests/screenshots/06-wide.png',fullPage:true});
 await page.getByRole('button',{name:'⚙ 设置'}).click();await page.getByRole('button',{name:'退出登录'}).click();await expect(page.getByLabel('登录密码')).toBeVisible();expect(errors).toEqual([]);
});

test('回到前台时关闭已经失效的图片',async({page})=>{
 await page.goto('/');
 await page.getByLabel('云端地址').fill('http://127.0.0.1:18765');
 await page.getByLabel('登录密码').fill('local-test-password');
 await page.getByRole('button',{name:'连接我的图库'}).click();
 await page.locator('.tile').first().click();
 await expect(page.getByRole('dialog')).toBeVisible();
 await page.route(/\/api\/images\/[a-f0-9]{64}$/,route=>route.fulfill({
  status:404,json:{detail:'图片不存在或已过期'}
 }));
 await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.getByRole('status')).toContainText('图片不存在或已过期');
});

test('从图库删除图片后重新查询并保留筛选',async({page},testInfo)=>{
 const errors:string[]=[];
 const detailUrl=/\/api\/images\/[a-f0-9]{64}$/;
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',message=>{
  if(message.type()==='error'&&!(detailUrl.test(message.location().url)&&message.text().includes('409'))){
   errors.push(message.text());
  }
 });
 await page.goto('/');
 await page.getByLabel('云端地址').fill('http://127.0.0.1:18765');
 await page.getByLabel('登录密码').fill('local-test-password');
 await page.getByRole('button',{name:'连接我的图库'}).click();
 const search=page.getByLabel('搜索图片');
 const cards=page.locator('.tile');
 await expect(cards).toHaveCount(6);
 const listRequest=(url:string)=>new URL(url).pathname==='/api/images';
 const filtered=page.waitForResponse(response=>listRequest(response.url())&&new URL(response.url()).searchParams.get('q')==='山色');
 await search.fill('山色');
 await filtered;
 await expect(cards).toHaveCount(6);
 await expect(cards.locator('img')).toHaveCount(6);
 await page.screenshot({path:testInfo.outputPath('gallery-delete-mobile.png')});
 await page.setViewportSize({width:1100,height:850});
 await page.screenshot({path:testInfo.outputPath('gallery-delete-desktop.png')});
 const remove=cards.first().getByRole('button',{name:'删除图片'});
 const requests:string[]=[];
 page.on('request',request=>{
  if(request.method()==='DELETE'||listRequest(request.url()))requests.push(request.method());
 });

 page.once('dialog',dialog=>dialog.dismiss());
 await remove.click();
 await expect(cards).toHaveCount(6);
 await expect(page.getByRole('dialog')).toHaveCount(0);
 expect(requests).toEqual([]);

 await page.route(detailUrl,route=>route.request().method()==='DELETE'
  ? route.fulfill({status:409,json:{detail:'暂时无法删除'},headers:{'Access-Control-Allow-Origin':'http://127.0.0.1:5173'}})
  : route.continue());
 page.once('dialog',dialog=>dialog.accept());
 await remove.click();
 await expect(page.getByRole('alert')).toContainText('暂时无法删除');
 await expect(cards).toHaveCount(6);
 expect(requests).toEqual(['DELETE']);
 await page.screenshot({path:testInfo.outputPath('gallery-delete-failed.png')});
 await page.unroute(detailUrl);

 const deleted=page.waitForResponse(response=>response.request().method()==='DELETE'&&response.ok());
 const refreshed=page.waitForResponse(response=>listRequest(response.url()));
 let confirmation='';
 page.once('dialog',dialog=>{confirmation=dialog.message();return dialog.accept();});
 await remove.click();
 const response=await deleted;
 const after=await refreshed;
 expect(confirmation).toContain('永久删除这张图片及其全部来源记录');
 expect(new URL(after.url()).searchParams.get('q')).toBe('山色');
 const removedId=new URL(response.url()).pathname.split('/').pop();
 const listing=await after.json();
 expect(listing.total).toBe(5);
 expect(listing.items.map((item:{id:string})=>item.id)).not.toContain(removedId);
 await expect(cards).toHaveCount(5);
 await expect(search).toHaveValue('山色');
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.getByRole('status')).toContainText('图片已删除');
 expect(requests).toEqual(['DELETE','DELETE','GET']);
 expect(errors).toEqual([]);
 await page.screenshot({path:testInfo.outputPath('gallery-delete-success.png')});
});

test('在设置中保存识别时间、规则并提交试跑',async({page},testInfo)=>{
 const errors:string[]=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
 await page.goto('/');
 await page.getByLabel('云端地址').fill('http://127.0.0.1:18765');
 await page.getByLabel('登录密码').fill('local-test-password');
 await page.getByRole('button',{name:'连接我的图库'}).click();
 await page.getByRole('button',{name:'⚙ 设置'}).click();
 const time=page.getByLabel('每日识别时间（北京时间）');
 const prompt=page.getByLabel('图片保留规则');
 await time.fill('22:15');
 await prompt.fill('保留同人插画，纯聊天截图可删除。角色看不清时待确认。');
 await page.getByLabel('将符合规则的图片自动收藏').check();
 await page.getByLabel('启用定时识别和自动删除').check();
 await page.getByRole('button',{name:'保存识别设置'}).click();
 await expect(page.getByText('识别设置已保存')).toBeVisible();
 await expect(page.getByText(/下一批.*22:15/)).toBeVisible();
 await page.getByRole('button',{name:'▧ 图库'}).click();
 await page.getByRole('button',{name:'⚙ 设置'}).click();
 await expect(time).toHaveValue('22:15');
 await expect(prompt).toHaveValue('保留同人插画，纯聊天截图可删除。角色看不清时待确认。');
 await expect(page.getByLabel('将符合规则的图片自动收藏')).toBeChecked();
 await page.setViewportSize({width:412,height:1050});
 await page.locator('.ai-review').screenshot({path:testInfo.outputPath('ai-review-mobile.png')});
 await page.setViewportSize({width:1100,height:1300});
 await page.getByRole('button',{name:'试跑规则'}).click();
 await expect(page.getByRole('heading',{name:'最近一次试跑'})).toBeVisible();
 await expect(page.getByText('待处理').first()).toBeVisible();
 await expect(page.getByRole('button',{name:'试跑规则'})).toBeDisabled();
 const samples=page.locator('.ai-preview li');
 await expect(samples.locator('img')).toHaveCount(await samples.count());
 await page.locator('.ai-review').screenshot({path:testInfo.outputPath('ai-review-desktop.png')});
 expect(errors).toEqual([]);
});
