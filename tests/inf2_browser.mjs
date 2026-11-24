// Optional Windows browser acceptance. The dashboard itself has no Node dependency.
import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {existsSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import path from "node:path";
import {setTimeout as delay} from "node:timers/promises";

const root = process.cwd();
const home = process.argv[2] || "inf2-browser";
const port = 8767;
const browserPath = process.env.INF2_EDGE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const base = path.join(root,"logs","inf1");
const output = path.join(base,home);
const imageDir = path.join(root,"docs","images");
const smoke = path.join(output,"jobs","inf2-smoke");
const load = file => JSON.parse(readFileSync(file,"utf8"));
const observations = [];
const record = (name, details = {}) => {
  observations.push({name, ...details});
  writeFileSync(path.join(output,"browser-evidence.json"), JSON.stringify(observations,null,2)+"\n");
  process.stdout.write(name+"\n");
};

async function until(check, name, timeout = 30000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; }
    catch (error) { last = error; }
    await delay(110);
  }
  throw new Error(name + (last ? ": " + last.message : ""));
}
function launcher(queue, number, defaultBrowser) {
  const args = ["tools\\training_manager\\start-dashboard.cmd", "--home", queue, "--port", String(number)];
  if (!defaultBrowser) args.push("--no-browser");
  const run = spawnSync("cmd.exe",["/d","/c",...args],{encoding:"utf8",timeout:20000,input:"\r\n"});
  assert.equal(run.status,0,run.error?.message || run.stderr || run.stdout);
}
function recordFor(queue) { return load(path.join(base,queue,"dashboard-instance.json")); }

class DevTools {
  constructor(address) {
    this.socket = new WebSocket(address);
    this.ready = new Promise((resolve,reject) => {
      this.socket.addEventListener("open",resolve,{once:true});
      this.socket.addEventListener("error",reject,{once:true});
    });
    this.serial = 0;
    this.pending = new Map();
    this.socket.addEventListener("message",message => {
      const body = JSON.parse(message.data);
      const pending = this.pending.get(body.id);
      if (!pending) return;
      this.pending.delete(body.id);
      if (body.error) pending.reject(new Error(body.error.message));
      else pending.resolve(body.result);
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("Browser closed"));
      this.pending.clear();
    });
  }
  async send(method,params = {}) {
    await this.ready;
    const id = ++this.serial;
    return new Promise((resolve,reject) => {
      this.pending.set(id,{resolve,reject});
      this.socket.send(JSON.stringify({id,method,params}));
    });
  }
  async eval(expression) {
    const response = await this.send("Runtime.evaluate",{expression, returnByValue:true, awaitPromise:true});
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || "Browser evaluation failed");
    return response.result.value;
  }
  async click(label, scope = "document") {
    const find = `(() => {
      const button = [...(${scope}).querySelectorAll('button')].find(x =>
        (x.dataset.page ? x.lastChild.textContent : x.textContent).trim() === ${JSON.stringify(label)} && !x.disabled);
      if (!button || (document.querySelector('dialog').open && !button.closest('dialog'))) return null;
      button.scrollIntoView({block:'center'});
      const r = button.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+r.height/2};
    })()`;
    const xy = await until(() => this.eval(find),"Missing button "+label,15000);
    for (const type of ["mousePressed","mouseReleased"]) {
      await this.send("Input.dispatchMouseEvent",{type,...xy,button:"left",clickCount:1});
    }
  }
  text(value) {
    return this.eval(`document.body.innerText.includes(${JSON.stringify(value)})`);
  }
  async capture(file, scrollTop = true) {
    if (scrollTop) await this.eval("window.scrollTo(0,0); true");
    const data = await this.send("Page.captureScreenshot",{format:"png",fromSurface:true});
    writeFileSync(path.join(imageDir,file),Buffer.from(data.data,"base64"));
  }
}
async function browser(name) {
  const profile = path.join(output,name);
  mkdirSync(profile,{recursive:true});
  const child = spawn(browserPath,["--headless=new","--no-first-run","--disable-gpu","--remote-debugging-port=0",
    "--remote-debugging-address=127.0.0.1","--user-data-dir="+profile,"--window-size=1390,975","about:blank"],{stdio:"ignore"});
  const active = path.join(profile,"DevToolsActivePort");
  const number = await until(() => existsSync(active) && readFileSync(active,"utf8").split(/\r?\n/)[0],"Edge startup");
  const debug = "http://127.0.0.1:"+number;
  const list = await fetch(debug+"/json/list").then(r => r.json());
  const controller = new DevTools(list.find(t => t.type === "page").webSocketDebuggerUrl);
  const version = await fetch(debug+"/json/version").then(r => r.json());
  const connection = new DevTools(version.webSocketDebuggerUrl);
  await controller.send("Emulation.setDeviceMetricsOverride",{width:1390,height:940,deviceScaleFactor:1,mobile:false});
  return {controller, connection, child};
}
async function open(tab, queue, portNumber) {
  await tab.send("Page.navigate",{url:`http://127.0.0.1:${portNumber}/#${recordFor(queue).proof}`});
  await until(() => tab.text("本地面板已连接"),"Dashboard did not connect");
}
async function stopManager(tab) {
  await tab.click("训练总览");
  await tab.click("安全关闭管理器");
  await tab.click("确认关闭管理器");
  await until(() => tab.text("离线"),"Manager did not stop",90000);
  await until(() => tab.eval("!document.querySelector('dialog').open"),"Shutdown dialog did not close");
}
async function stopPanel(tab) {
  await tab.click("资源与设置");
  await tab.click("关闭面板服务");
  await tab.click("确认关闭面板服务");
  await until(() => tab.text("面板已关闭"),"Panel did not close");
}
function readTraining() {
  const file = path.join(smoke,"training","progress.json");
  return existsSync(file) ? load(file).done : 0;
}
function apiCall(portNumber, name, body, auth = {}) {
  const url = "http://127.0.0.1:"+portNumber;
  return fetch(url+"/api/"+name, body === undefined ? {headers:auth} : {
    method:"POST",body:JSON.stringify(body),headers:{"Content-Type":"application/json",Origin:url,...auth}
  }).then(async response => ({code:response.status, headers:response.headers, data:await response.json()}));
}
async function authorized(queue, number) {
  const handshake = await apiCall(number,"session",{proof:recordFor(queue).proof});
  assert.equal(handshake.code,200);
  return {Cookie:handshake.headers.get("set-cookie").split(";")[0],"X-INF2-CSRF":handshake.data.csrf};
}

assert.ok(!existsSync(output),"Use a fresh isolated acceptance queue");
mkdirSync(output,{recursive:true});
mkdirSync(imageDir,{recursive:true});
let edge;
let launchedTest = false;
let launchedDefault = false;
try {
  launcher(home,port,true);
  launchedTest = true;
  record("Windows launcher opened default browser");
  const instance = recordFor(home);
  launcher(home,port,false);
  assert.equal(instance.proof,recordFor(home).proof);
  record("Duplicate launcher reused loopback service");
  const defaultHealth = await fetch("http://127.0.0.1:8765/health").then(r => r.ok).catch(() => false);
  if (!defaultHealth) {
    launcher(".",8765,false);
    launchedDefault = true;
  }
  edge = await browser("edge-first");
  let tab = edge.controller;
  await open(tab,".",8765);
  await tab.click("训练计划");
  await until(() => tab.text("初始训练尚未提交"),"DC2B gate not shown");
  await tab.capture("inf2-plans.png");
  const formalAuth = await authorized(".",8765);
  const gated = await apiCall(8765,"action/freeze",{id:"dc2b-curriculum"},formalAuth);
  assert.equal(gated.code,409);
  assert.ok(gated.data.error.includes("初始训练尚未提交"));
  record("Formal curriculum blocked before submission");
  await open(tab,home,port);
  const testAuth = await authorized(home,port);
  const first = await apiCall(port,"state",undefined,testAuth);
  assert.equal(first.data.online,false);
  assert.equal(first.data.tasks.length,0);
  assert.equal(first.data.mode,"Idle");
  await tab.click("启动管理器");
  await tab.click("确认启动管理器");
  await until(() => tab.text("在线"),"Manager did not start");
  record("Browser started standalone INF1");
  await tab.click("资源与设置");
  for (const [mode,caption] of [["Light","低负载模式"],["Full","全速模式"],["Idle","空闲模式"],["Full","全速模式"]]) {
    await tab.click(mode+" · "+caption);
    await tab.click("确认切换模式");
    await until(async () => (await apiCall(port,"state",undefined,testAuth)).data.mode === mode,"Mode did not switch");
    await until(() => tab.eval("!document.querySelector('dialog').open"),"Mode dialog did not close");
  }
  record("Browser selected Light, Full, Idle and Full");
  await tab.click("训练计划");
  await until(() => tab.text("INF2 面板验收"),"Smoke plan unavailable");
  await tab.click("审核计划", "[...document.querySelectorAll('article')].find(a=>a.textContent.includes('INF2 面板验收'))");
  await tab.click("冻结并查看配置");
  await until(() => tab.text("任务配置 SHA-256"),"Freeze was not displayed");
  assert.equal((await apiCall(port,"state",undefined,testAuth)).data.tasks.length,0);
  await tab.click("确认提交到 INF1");
  await until(() => tab.text("当前阶段已提交"),"No measured training progress",120000);
  await until(() => readTraining() >= 4,"No committed optimizer checkpoint",120000);
  await tab.click("安全暂停");
  await until(async () => {
    const current = (await apiCall(port,"state",undefined,testAuth)).data.tasks[0];
    return current.state === "paused" && current.stage === "training";
  },"Training did not pause at its checkpoint",90000);
  const paused = readTraining();
  assert.ok(paused >= 4 && paused < 80);
  await until(() => tab.text("已暂停"),"Paused state not displayed");
  assert.ok(await tab.text("用户请求安全暂停"));
  assert.ok(await tab.text("logs/inf1/"));
  await tab.capture("inf2-queue.png");
  await tab.click("任务详情");
  await until(() => tab.text("任务详情 · inf2-smoke"),"Job detail not displayed");
  await until(() => tab.eval(`[...document.querySelectorAll('dialog summary')].some(x=>x.textContent.includes('日志、检查点'))`),
    "Artifact links not displayed");
  await tab.click("关闭");
  record("GPU training paused at committed optimizer checkpoint",{updates:paused});
  await tab.click("恢复任务");
  await until(async () => (await apiCall(port,"state",undefined,testAuth)).data.tasks[0].state === "running","No resumed task");
  const lastSeen = readTraining();
  await edge.connection.send("Browser.close").catch(() => {});
  await until(() => edge.child.exitCode !== null,"Browser process did not close",20000);
  await until(() => readTraining() > lastSeen,"Work did not advance after browser closed",90000);
  record("Training advanced after closing browser",{before:lastSeen,after:readTraining()});
  edge = await browser("edge-reopened");
  tab = edge.controller;
  await open(tab,home,port);
  await until(async () => (await apiCall(port,"state",undefined,testAuth)).data.tasks[0].state === "completed",
    "Real development task did not complete",180000);
  await tab.click("训练结果");
  await until(() => tab.text("80"),"Real training result missing");
  await edge.connection.send("Browser.grantPermissions",{origin:`http://127.0.0.1:${port}`,
    permissions:["clipboardReadWrite","clipboardSanitizedWrite"]});
  const previousClipboard = await tab.eval("navigator.clipboard.readText().catch(() => null)");
  await tab.click("复制 Markdown 摘要");
  await until(() => tab.text("已复制 Markdown 实验摘要"),"Clipboard confirmation not displayed");
  const markdown = await tab.eval("navigator.clipboard.readText()");
  assert.ok(markdown.includes("inf2-smoke") && markdown.includes("更新 80"));
  writeFileSync(path.join(output,"copied-summary.md"),markdown);
  if (previousClipboard !== null) await tab.eval(`navigator.clipboard.writeText(${JSON.stringify(previousClipboard)})`);
  await tab.capture("inf2-results.png");
  await tab.eval(`[...document.querySelectorAll('#content h2')].find(x=>x.textContent==='inf2-smoke').closest('section')
    .scrollIntoView({block:'start'}); true`);
  await tab.capture("inf2-training.png",false);
  record("Reopened browser showed real results and copied Markdown",{updates:80,development:8});
  await tab.click("训练总览");
  await tab.click("安全暂停所有计算");
  await tab.click("确认暂停所有计算");
  await until(() => tab.text("已停止"),"Scheduling not stopped");
  await stopManager(tab);
  await stopPanel(tab);
  record("All scheduling stopped; INF1 and test web service closed");
} finally {
  if (edge) {
    edge.connection.send("Browser.close").catch(() => {});
    edge.controller.socket.close();
    await until(() => edge.child.exitCode !== null,"Edge cleanup",12000).catch(() => edge.child.kill());
  }
  for (const [queue,number,owned] of [[home,port,launchedTest],[".",8765,launchedDefault]]) {
    if (!owned) continue;
    try {
      const auth = await authorized(queue,number);
      if (queue === home) {
        await apiCall(number,"action/shutdown",{},auth);
        await until(async () => !(await apiCall(number,"state",undefined,auth)).data.online,
          "INF1 cleanup",90000);
      }
      await apiCall(number,"action/close-panel",{},auth);
    } catch (error) {
      if (!["ECONNREFUSED","ECONNRESET","UND_ERR_SOCKET"].includes(error.cause?.code))
        process.stderr.write(error.message+"\n");
    }
  }
}
