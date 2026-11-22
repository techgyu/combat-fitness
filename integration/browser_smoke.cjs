// node integration/browser_smoke.cjs <python.exe>; Playwright and Edge are required.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn}=require('node:child_process');
const {mkdtempSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
const repo=path.resolve(__dirname,'..'), python=process.argv[2] || 'python';
const temp=mkdtempSync(path.join(tmpdir(),'fitness-system-browser-'));
const workers=[];
function start(args){const p=spawn(python,['-X','utf8',...args],{windowsHide:true,stdio:['ignore','pipe','pipe']});workers.push(p);p.stderr.on('data',d=>process.stderr.write(d));return p;}
async function ready(url){for(let i=0;i<80;i++){try{if((await fetch(url)).ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('Server did not start: '+url);}
async function run(){
 let browser;
 try{
  start([path.join(repo,'tests/http_fixture_server.py'),'--port','18501']);
  await ready('http://127.0.0.1:18501/health');
  start([path.join(repo,'backend/module1/server.py'),'--port','18500','--db',path.join(temp,'web.sqlite3'),'--module2-url','http://127.0.0.1:18501']);
  await ready('http://127.0.0.1:18500/api/v1/health');
  browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:18500/');
  await page.locator('#detailTitle').filter({hasText:'26-00000001'}).waitFor();
  await page.locator('#showForm').click();
  await page.locator('[name=soldier_id]').fill('22-99999999');
  await page.locator('[name=pushups_2min]').fill('90');
  await page.locator('[name=situps_2min]').fill('100');
  await page.locator('[name=run_3km_time]').fill('11:40');
  await page.locator('#saveButton').click();
  await page.locator('#detailTitle').filter({hasText:'22-99999999'}).waitFor();
  assert.deepEqual(JSON.parse(await page.locator('#jsonPreview').textContent()).difference_matrix,[[-26,-22,112,0]]);
  await page.locator('#sendModule2').click();
  await page.locator('#planStatus').filter({hasText:'등록 규칙 검증 통과'}).waitFor();
  assert.equal(await page.locator('.week-plan').count(),8);
  assert.equal(await page.locator('#planNeeds').textContent().then(t=>(t.match(/현재 수준 유지/g)||[]).length),3);
  assert.equal(await page.locator('#planWeeks tbody tr').count(),46);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.join(temp,'desktop.png'),fullPage:true});
  await page.reload();
  await page.locator('#search').fill('22-99999999');
  await page.locator('#searchForm button').click();
  await page.getByRole('button',{name:'22-99999999',exact:true}).click();
  await page.locator('#planStatus').filter({hasText:'등록 규칙 검증 통과'}).waitFor();
  const download=page.waitForEvent('download');await page.locator('#downloadPlan').click();
  assert.match((await download).suggestedFilename(),/_8week_plan.json$/);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(temp,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',claude:'scripted test output',checks:['web_input','fixed_goal_above_reference','real_http_hops','8_weeks_46_rows','maintain_above_reference','sqlite_reload','plan_download','mobile_no_overflow','no_js_errors'],screenshots:temp}));
 }finally{if(browser)await browser.close();for(const p of workers)p.kill();}
}
run().catch(e=>{console.error(e);process.exitCode=1;});
