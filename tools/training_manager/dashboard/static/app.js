"use strict";

const pages = {
  overview: ["训练总览", "查看训练进度和调度状态。"],
  plans: ["训练计划", "审核仓库计划，冻结输入身份，再确认提交。"],
  queue: ["任务队列", "管理已提交任务，并查看日志与有效检查点。"],
  results: ["训练结果", "查看实际开发评测、训练指标与实验产物。"],
  resources: ["资源与设置", "查看本机资源，调整运行模式及安全阈值。"]
};
const states = {
  queued: "等待调度", running: "运行中", pausing: "正在等待安全检查点", paused: "已暂停",
  completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断"
};
const stages = {
  "cache-d2": "D2 特征缓存", "cache-d2-search": "D2 搜索特征缓存", initial: "初始 CUDA 训练",
  development: "原开发集评测", gate: "开发退化检查", "complex-baseline": "复杂构筑 D2 对照",
  "complex-development": "复杂构筑开发评测", training: "小规模续训", experience: "经验生产", features: "构建训练特征"
};
const stageParts = {
  direct: "直接经验", "direct-cache": "直接经验特征", search: "搜索经验", "search-cache": "搜索经验特征",
  fit: "CUDA 训练", development: "开发评测", complex: "复杂构筑开发评测"
};
const modes = {Full: "全速模式", Idle: "空闲模式", Light: "低负载模式"};
const labels = {
  idle_seconds: "空闲门槛（秒）", min_disk_mb: "最低磁盘（MiB）", min_ram_mb: "最低可用内存（MiB）",
  min_vram_mb: "最低空闲显存（MiB）", resource_samples: "连续不足采样次数", require_ac: "运行要求接通电源"
};
const modesCopy = {
  Full: "全速模式使用计划已批准的正常资源预算。",
  Idle: "空闲模式要求插电，并达到配置的无输入时长后发车。",
  Light: "GPU 与未提供低负载参数的高负载阶段会等待。"
};
const el = id => document.getElementById(id);
const content = el("content"), modal = el("modal"), modalBody = el("modal-body");
let page = "overview", csrf = null, state = null, epoch = 0, reviewed = null, timer, actionBusy = false;

function node(tag, value, css) {
  const element = document.createElement(tag);
  if (css) element.className = css;
  if (value != null) element.textContent = value;
  return element;
}

function add(parent, ...children) {
  parent.append(...children.filter(child => child != null));
  return parent;
}

function action(label, callback, css = "secondary", disabled = false) {
  const button = node("button", label, "button " + css);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await callback(); }
    catch (error) { notify(error.message, true); }
    finally { button.disabled = disabled; }
  });
  return button;
}

function notify(value, error = false) {
  const notice = el("notice");
  notice.hidden = false;
  notice.textContent = value;
  notice.classList.toggle("error", error);
  clearTimeout(timer);
  timer = setTimeout(() => { notice.hidden = true; }, error ? 9000 : 4500);
}

async function api(path, body) {
  const options = {credentials: "same-origin", cache: "no-store"};
  if (body !== undefined) {
    options.method = "POST";
    options.body = JSON.stringify(body);
    options.headers = {"Content-Type":"application/json", "X-INF2-CSRF":csrf || ""};
  }
  const response = await fetch("/api/" + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "读取面板失败");
  return data;
}

function pill(text, code) { return node("span", text, "pill " + (code || "")); }
function stat(title, value) { return add(node("div", null, "card"), node("div", title, "stat-name"), node("span", value, "stat-value")); }
function card(title, ...children) {
  return add(node("section", null, "card"), node("h2", title), ...children);
}
function bar(...children) { return add(node("div", null, "actions"), ...children); }
function dataList(pairs) {
  const list = node("dl", null, "metadata");
  for (const [term, value] of pairs) add(list, add(node("div"), node("dt", term), node("dd", value ?? "不可用")));
  return list;
}
function table(headers, rows) {
  const wrap = node("div", null, "table-scroll"), t = node("table"), head = node("tr"), body = node("tbody");
  for (const header of headers) add(head, node("th", header));
  for (const row of rows) {
    const tr = node("tr");
    for (const cell of row) add(tr, cell instanceof Node ? add(node("td"), cell) : node("td", cell ?? "尚未生成"));
    add(body, tr);
  }
  return add(wrap, add(t, add(node("thead"), head), body));
}
function disclosure(title, body) { return add(node("details"), node("summary", title), body); }
function callout(value, code = "") { return node("p", value, "callout " + code); }
function n(value, precision = 2) { return typeof value === "number" ? value.toLocaleString("zh-CN", {maximumFractionDigits:precision}) : "不可用"; }
function pct(value) { return typeof value === "number" ? n(value*100, 2) + "%" : "尚未生成"; }
function duration(seconds) {
  if (seconds == null) return "不可用";
  seconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds / 60) % 60;
  return (hours ? `${hours} 小时 ` : "") + (minutes ? `${minutes} 分 ` : "") + `${seconds % 60} 秒`;
}
function stage(id) {
  if (!id) return "—";
  if (stages[id]) return stages[id];
  const match = /^g(\d+)-(.+)$/.exec(id);
  return match && stageParts[match[2]] ? `G${match[1]} · ${stageParts[match[2]]}` : id;
}
function reason(value) {
  const translations = {
    "manager stopped": "调度已停止", "Light mode excludes this stage": "此阶段在 Light 模式下等待",
    "AC unavailable": "等待交流电源", "waiting for input idle": "等待达到输入空闲门槛",
    "resource profile changed": "资源档位已改变，正在切换", budget:"达到受监督执行预算",
    "attempt exited without a result": "工作进程未返回退出记录", pause: "用户请求暂停", automatic:"等待资源允许",
    cancel:"用户请求安全取消", force:"用户请求立即终止"
  };
  const metric = /^(ram_mb|disk_mb) below (\d+) or unavailable$/.exec(value || "");
  if (metric) return `等待${metric[1] === "ram_mb" ? "可用内存" : "磁盘空间"}达到 ${metric[2]} MiB`;
  if (value?.startsWith("GPU 0")) return "GPU 0 不可用或空闲显存不足";
  return translations[value] || value;
}
function show(title, ...body) {
  el("modal-title").textContent = title;
  modalBody.replaceChildren(...body.filter(Boolean));
  if (!modal.open) modal.showModal();
}
function confirmAction(title, message, callback, css = "") {
  show(title, node("p", message), bar(action("返回", () => modal.close()), action("确认" + title, async () => {
    await callback();
    modal.close();
  }, css)));
}
async function operate(op, details = {}, toast = "已提交操作，状态将随 INF1 更新。") {
  if (actionBusy) throw new Error("正在处理另一项操作，请稍候");
  actionBusy = true;
  try {
    const result = await api("action/" + op, details);
    notify(toast);
    if (op !== "close-panel") await loadPage();
    return result;
  } finally { actionBusy = false; }
}

function progress(label, done, target) {
  const barElement = node("progress");
  barElement.max = Math.max(1, target);
  barElement.value = done;
  barElement.setAttribute("aria-label", label);
  return add(node("div", null, "progress-wrap"),
    add(node("div", null, "progress-line"), node("strong", label), node("span", `${n(done,0)} / ${n(target,0)}`)), barElement);
}
function taskCard(task) {
  const p = task.progress;
  const live = ["running", "pausing"].includes(task.state);
  const container = card(task.name, dataList([
    ["当前阶段", stage(task.stage)], ["已确认执行", duration(task.seconds)],
    ["暂停（自然时间）", duration(task.paused_seconds)],
    ["任务离线", task.timing?.offline_seconds == null ? "未测定" : duration(task.timing.offline_seconds)],
    ["剩余执行预算", task.budget == null ? "未设定" : task.timing?.unknown_tail ?
      (live ? "等待执行心跳" : "需另行批准") : duration(task.budget - task.seconds)],
    ["实际吞吐", p?.throughput > 0 ? n(p.throughput) + " 单位/秒" : "不可用"]
  ]), progress("总体阶段进度", task.stage_index, task.stage_total));
  if (task.audit_blocker) add(container, callout("续接校验阻塞：" + task.audit_blocker, "warn"));
  if (task.timing?.unknown_tail) add(container, callout(task.timing.audited ?
    "原面板记录 " + duration(task.timing.legacy_recorded_seconds) + "。审计执行区间 " +
      duration(task.seconds) + " 至 " + duration(task.timing.upper_seconds) + "。" :
    "执行尾段无法确认，已显示最近心跳确认的执行量。", "warn"));
  add(container, p ? progress("当前阶段已提交", p.done, p.target) :
    node("p", "当前阶段未提供精确内部进度。", "muted progress-wrap"));
  if (p && (p.attempts != null || p.updates != null || p.complete != null)) {
    add(container, dataList([["完整经验/结果", p.complete], ["尝试", p.attempts == null ? null :
      `${n(p.attempts,0)} / ${n(p.attempt_limit,0)}`], ["已提交优化更新", p.updates]]));
  }
  if (task.state === "running" && p?.throughput > 0 && (p.measured_units ?? p.done) >= 8 &&
      p.target > p.done && task.seconds >= 10) {
    add(container, node("p", "阶段预计剩余 " + duration((p.target-p.done)/p.throughput) +
      "，按实测速率估算，与执行预算分别计算。", "muted"));
  }
  if (p?.checkpoint) add(container, node("p", "最近有效检查点  " + p.checkpoint, "detail-path"));
  if (task.reason || task.intent === "pause") add(container, callout(
    task.intent === "pause" ? "用户请求安全暂停" : reason(task.reason), task.state === "failed" ? "error" : "warn"));
  add(container, taskActions(task));
  return container;
}
function taskActions(task) {
  if (task.timing?.audited || task.audit_blocker) return bar(action("中断诊断", () => jobDetail(task.id)),
    action("查看续接计划", () => { if (modal.open) modal.close(); return navigate("plans"); }));
  const command = op => operate(op, {id:task.id});
  const cancellable = ["queued","running","pausing","paused","failed","interrupted"].includes(task.state);
  return bar(
    action("任务详情", () => jobDetail(task.id)),
    ["queued","running"].includes(task.state) ? action("安全暂停", () => command("pause")) : null,
    task.state === "paused" ? action("恢复任务", () => command("resume"), "") : null,
    task.retryable ? action("重试", () => confirmAction("重试任务", "将使用一次已批准的重试额度。", () => command("retry"))) : null,
    cancellable ? action("安全取消", () => confirmAction("安全取消", "INF1 会等待当前安全边界。取消后的任务不再进入调度。", () => command("cancel"), "danger")) : null,
    ["running","pausing"].includes(task.state) ? action("立即强制取消", () => confirmAction("强制取消",
      "立即结束这个任务的进程树。未提交的工作可能丢失，请确认任务身份。", () => command("force"), "danger"), "danger") : null);
}
function overview() {
  const active = state.tasks.find(task => ["running","pausing"].includes(task.state));
  const paused = state.tasks.filter(task => task.state === "paused");
  const pending = state.tasks.filter(task => task.state === "queued");
  const totals = add(node("div", null, "stat-grid"),
    stat("INF1 管理器", state.closing ? "正在安全关闭" : state.online ? "在线" : "离线"),
    stat("任务调度", state.enabled ? "已允许" : "已停止"),
    stat("运行模式", state.mode + " · " + modes[state.mode]));
  const controlCard = card("调度控制",
    bar(action("启动管理器", () => confirmAction("启动管理器",
      "如果调度已允许且任务符合资源条件，INF1 将开始执行队列。", () => operate("start")), "", state.online),
    action(state.enabled ? "允许调度" : "恢复调度", () => confirmAction("允许调度",
      "符合运行模式及资源条件的任务可以继续运行。手动暂停的任务需单独恢复。", () => operate("enable")),
    "secondary", state.enabled || state.closing)),
    bar(action("安全暂停所有计算", () => confirmAction("暂停所有计算",
      "停止发车，并让活动任务退出到安全边界。", () => operate("stop-all"))),
    action("安全关闭管理器", () => confirmAction("关闭管理器",
      "结束调度并等待活动任务安全退出。下次启动后可手动恢复调度。", () => operate("shutdown")),
    "secondary", !state.online)),
    node("p", "关闭浏览器不会改变 INF1 的运行或调度状态。", "callout"));
  const current = active || paused[0] || pending[0];
  const main = current ? taskCard(current) : card("当前任务", node("p", "没有正在运行或等待的任务。", "empty"),
      bar(action("查看训练计划", () => navigate("plans"))));
  if (current) main.firstChild.replaceWith(add(node("div", null, "card-head"), node("h2", current.name),
    pill(states[current.state], current.state)));
  return [totals, add(node("div", null, "columns"), main, controlCard),
    card("队列概况", dataList([["待调度", pending.length],["已暂停", paused.length],
      ["已完成", state.tasks.filter(task => task.state === "completed").length]]),
    bar(action("打开任务队列", () => navigate("queue"))))];
}

function argsOption(stage, flag) {
  const index = stage.args.indexOf(flag);
  return index < 0 ? undefined : stage.args[index+1];
}
function planDetails(item) {
  const spec = item.spec, limits = spec.limits || {};
  const modelInputs = new Set();
  for (const input of Array.isArray(spec.inputs) ? spec.inputs : Object.keys(spec.inputs)) {
    if (input.endsWith(".pt")) modelInputs.add(input);
  }
  return [
    dataList([["任务 ID", spec.id],["最大代数", limits.generations ?? "未设定"],
      ["优化更新", limits.optimizer_updates == null ? "未设定" : n(limits.optimizer_updates,0)],
      ["完整经验目标", limits.experience_roots == null ? "未设定" : n(limits.experience_roots,0)],
      ["最大经验尝试", limits.experience_attempts == null ? "未设定" : n(limits.experience_attempts,0)],
      ["运行预算上限", spec.budget_seconds == null ? "未设定" : duration(spec.budget_seconds)],
      ["原开发评测根", limits.development_roots ?? "未设定"],
      ["正式确认场次", limits.confirmation_evaluations ?? "未设定"]]),
    node("p", "输出目录  " + spec.output, "detail-path"),
    ...(modelInputs.size ? [node("p", "输入模型  " + [...modelInputs].join("、"), "detail-path")] : []),
    disclosure("阶段、依赖与实际参数", table(["阶段", "依赖", "实际任务量", "安全边界"],
      spec.stages.map(s => [stage(s.id), s.depends_on.map(stage).join("、") || "可开始",
        [argsOption(s,"--target") && "目标 " + argsOption(s,"--target"), argsOption(s,"--count") &&
          (argsOption(s,"--count") === "9999" ? "使用全部冻结复杂构筑开发根" : "最多 " + argsOption(s,"--count") + " 根"),
         argsOption(s,"--updates") && argsOption(s,"--updates") + " 次优化更新"].filter(Boolean).join(" · ") || "按配置",
        s.boundary === "Completed stage" ? "阶段完成" : s.boundary === "Committed optimizer or battle batch" ?
          "已提交的优化或战斗批次" : s.boundary]))),
    item.missing.length ? disclosure("缺少的资产", node("pre", item.missing.join("\n"))) : null
  ];
}
function reviewPlan(item) {
  const budget = node("input");
  budget.type = "number";
  budget.min = (item.spec.budget_reserve_seconds ?? item.spec.stop_grace_seconds ?? 180) + 1;
  budget.step = 1;
  budget.required = true;
  const recovery = item.recovery;
  show("审核 " + item.name, node("p", item.purpose), ...planDetails(item),
    recovery ? callout(`已审计 ${recovery.completed.length} 个成功阶段，保留 G1 / G2 和 G3 已提交的 ${recovery.g3.identity.count} 根。
      原执行范围 ${duration(recovery.timing.confirmed_seconds)} 至 ${duration(recovery.timing.upper_seconds)}。
      新预算由你单独批准。`) : null,
    recovery ? add(node("label", null, "settings-form"), node("span", "批准的新预算（秒）"), budget) : null,
    item.reasons.length ? callout(item.reasons.join("；"), "warn") : callout("冻结会核对资产并展示最终配置，提交需要再确认。"),
    bar(action("冻结并查看配置", async () => {
      if (recovery && !budget.reportValidity()) return;
      reviewed = await api("action/freeze", recovery ? {id:item.spec.id, budget_seconds:Number(budget.value)} : {id:item.spec.id});
      show("确认冻结配置", node("p", item.name),
        node("p", "任务配置 SHA-256  " + reviewed.spec.sha256, "detail-path"),
        node("pre", JSON.stringify(reviewed.spec, null, 2)),
        callout("确认提交后，符合当前调度及资源条件时可开始运行。"),
        bar(action("确认提交到 INF1", async () => {
          await operate("submit", {draft:reviewed.draft, sha256:reviewed.spec.sha256}, "任务已提交到 INF1。");
          modal.close();
          await navigate("queue");
        }, "")));
    }, "", item.reasons.length > 0)));
}
function plans(items) {
  return [add(node("div", null, "plans-grid"), ...items.map(item => {
    const limits = item.spec.limits || {};
    const title = add(node("div", null, "card-head"), node("h2", item.name),
      pill(item.reasons.length ? "暂不可提交" : "可审核", item.reasons.length ? "paused" : "online"));
    const box = add(node("article", null, "card"), title, node("p", item.purpose, "muted"),
      dataList([["更新预算", limits.optimizer_updates == null ? "未设定" : n(limits.optimizer_updates,0)],
        ["最大代数", limits.generations ?? "未设定"],["时间预算", duration(item.spec.budget_seconds)],
        ["资产就绪", `${item.asset_count-item.missing.length} / ${item.asset_count}`]]));
    if (item.reasons.length) add(box, callout(item.reasons.join("；"), "warn"));
    return add(box, bar(action("审核计划", () => reviewPlan(item))));
  }))];
}

async function fileView(id, name) {
  const data = await api("file?" + new URLSearchParams({id,name}));
  show(name, node("p", data.path + " · " + n(data.bytes,0) + " 字节", "detail-path"),
    data.content !== null ? node("pre", data.content) : node("p", "检查点为二进制文件。请在任务输出目录访问。"),
    data.truncated ? callout("长文件仅显示可用的预览部分。") : node("span"),
    bar(action("返回任务详情", () => jobDetail(id))));
}
async function jobDetail(id) {
  const report = await api("job?" + new URLSearchParams({id}));
  const task = state?.tasks.find(item => item.id === id);
  const files = report.files;
  const t = report.timing;
  const result = show("任务详情 · " + id, dataList([["状态", states[report.state]],["当前阶段", stage(report.current_stage)],
    ["已确认执行",duration(report.seconds)],["累计暂停",duration(report.paused_seconds)],
    ["任务离线",t?.offline_seconds == null ? "未测定" : duration(t.offline_seconds)],
    ["无法确认的执行尾段", t?.unknown_tail ? (t.upper_seconds == null ? "长度未测定" :
      "最多 " + duration(t.upper_seconds-report.seconds)) : "无记录"],
    ["退出码",report.exit_code],["异常次数",report.errors]]),
    report.audit_blocker ? callout("续接校验阻塞：" + report.audit_blocker, "warn") : null,
    node("p", "输出目录  " + report.spec.output, "detail-path"),
    disclosure("真实阶段与运行记录", node("pre", JSON.stringify(report, null, 2))),
    disclosure("日志、检查点及 JSON", add(node("div", null, "actions"),
      ...files.map(name => action(name, () => fileView(id, name))))),
    task ? taskActions(task) : node("span"),
    bar(action("在资源管理器打开输出目录", () => operate("folder", {id}))));
  return result;
}
function queue() {
  if (!state.tasks.length) return [card("任务队列", node("p", "尚未提交任务。", "empty"))];
  return [card("已提交任务", table(["任务", "状态", "阶段", "已确认执行", "操作"],
    [...state.tasks].reverse().map(task => [task.name, pill(states[task.state], task.state), stage(task.stage),
      duration(task.seconds), taskActions(task)]))),
    ...state.tasks.filter(task => ["running","pausing","paused","failed","interrupted"].includes(task.state)).map(taskCard)];
}

function chart(points) {
  const canvas = node("canvas", null, "curve");
  canvas.width = 760;
  canvas.height = 203;
  canvas.setAttribute("aria-label", "横轴为优化更新，纵轴为训练损失和验证 NLL");
  const ctx = canvas.getContext("2d");
  const start = points[0].updates, end = points.at(-1).updates;
  const values = points.flatMap(point => [point.loss,point.nll]).filter(Number.isFinite);
  if (!values.length) return canvas;
  const min = Math.min(...values), max = Math.max(...values);
  const x = point => 47 + (point.updates-start)/Math.max(1,end-start)*685;
  const y = value => 166 - (value-min)/Math.max(.001,max-min)*140;
  ctx.font = "13px Segoe UI";
  for (let i = 0; i <= 4; i++) {
    const height = 26+i*35;
    ctx.strokeStyle = "#dce7e4";
    ctx.beginPath(); ctx.moveTo(46,height); ctx.lineTo(733,height); ctx.stroke();
    ctx.fillStyle = "#526b65"; ctx.fillText(n(max-(max-min)*i/4),4,height+4);
  }
  ctx.fillText(n(start,0),47,190);
  ctx.fillText(n(end,0),700,190);
  for (const [field,color] of [["loss","#008978"],["nll","#b8712b"]]) {
    const samples = points.filter(point => Number.isFinite(point[field]));
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.beginPath();
    samples.forEach((point,i) => i ? ctx.lineTo(x(point), y(point[field])) : ctx.moveTo(x(point), y(point[field])));
    ctx.stroke();
    for (const point of samples) {
      ctx.beginPath(); ctx.arc(x(point), y(point[field]), 3, 0, 2*Math.PI); ctx.fill();
    }
  }
  return canvas;
}
async function copySummary(markdown) {
  try {
    await navigator.clipboard.writeText(markdown);
    notify("已复制 Markdown 实验摘要。");
  } catch {
    const text = node("textarea");
    text.rows = 15; text.cols = 64; text.value = markdown;
    show("Markdown 实验摘要", text, callout("已选中全文，可按 Ctrl+C 复制。"));
    text.select();
  }
}
function resultDetail(row) {
  const last = row.training.at(-1);
  const dev = row.development;
  const parts = [dataList([["实际优化更新", row.updates ?? "尚未生成"],
    ["训练累计运行", duration(row.training_seconds)], ["开发评测耗时", duration(dev?.seconds)]])];
  if (last) {
    addParts(parts, chart(row.training), node("p", "绿色 · 训练损失　　橙色 · 验证 NLL", "chart-key"),
      table(["最大 HP","验证样本","验证 NLL","死亡 Brier","胜局绝对净战损 MAE"],
        Object.entries(last.hp).map(([hp,m]) => [hp,m.n,n(m.nll,4),n(m.brier,4),n(m.mae,3)])));
  }
  const stratified = row.complex || dev;
  if (stratified && Object.keys(stratified.hp).length) {
    addParts(parts, node("h3", row.complex ? "复杂构筑开发分层" : "原开发分层"),
      table(["最大 HP","尝试","完整","胜率","平均净战损","零净战损胜率"],
        Object.entries(stratified.hp).filter(([,m]) => m.attempts).map(([hp,m]) =>
          [hp,m.attempts,m.complete,pct(m.win_rate),n(m.mean_net),pct(m.zero_net_win)])));
  }
  for (const [name, item] of Object.entries(row.production)) {
    addParts(parts, callout(`${stage(name)}：${item.complete} 完整 / ${item.attempts} 尝试`),
      dataList([["生产耗时",duration(item.wall_s)],["待诊断家族",item.diagnostics],
        ["课程晋级（符合条件的已排程家族）", item.promotion ? Object.entries(item.promotion).map(
          ([hp,count]) => `${hp} HP · ${count} 族`).join("，") : "尚未生成"],
        ["冻结配方中的 HP 分层", Object.entries(item.scheduled_families_by_hp).map(([hp,count]) => `${hp} HP · ${count} 族`).join("，") || "尚未生成"]]));
  }
  if (row.id) addParts(parts, bar(action("原始 JSON 与运行日志", () => jobDetail(row.id))));
  return card(row.name, ...parts);
}
function addParts(parts, ...items) { parts.push(...items); }
function results(data) {
  const fmt = value => value == null ? "尚未生成" : n(value);
  const rows = data.formal.map(row => {
    const dev = row.development, last = row.training.at(-1);
    return [row.name,fmt(dev?.attempts),pct(dev?.win),fmt(dev?.net),pct(dev?.zero),pct(dev?.low),
      fmt(row.updates),fmt(last?.brier),fmt(last?.mae)];
  });
  const gate = data.gate;
  const outcome = gate ? (gate.passed ? "已通过" : "未通过") : "尚未生成";
  return [card("开发集模型对比",
    table(["模型","尝试数","胜率","平均净战损","零净战损胜率","≤10 HP 胜率","更新数","死亡 Brier","绝对净战损 MAE"], rows),
    bar(action("复制 Markdown 摘要", () => copySummary(data.markdown), ""),
      action("预览 Markdown", () => show("Markdown 实验摘要", node("pre", data.markdown))))),
    card("开发退化检查", dataList([["结果",outcome],["配对数",gate?.comparison?.paired ?? "尚未生成"],
      ["共同完整",gate?.comparison?.joint_complete ?? "尚未生成"],
      ["胜率变化",pct(gate?.comparison?.win_delta)],["死亡率变化",pct(gate?.comparison?.death_delta)]]),
      ...(gate ? [disclosure("门槛原始 JSON", node("pre", JSON.stringify(gate,null,2)))] : [])),
    ...data.formal.filter(row => row.development || row.training.length || Object.keys(row.production).length).map(resultDetail),
    ...(data.smoke.length ? [card("隔离验收", node("p","验收产物按各自任务展示。","muted")),
      ...data.smoke.map(resultDetail)] : [])];
}

function resourcePage(data) {
  const modeSwitch = node("div", null, "mode-choice");
  for (const mode of Object.keys(modes)) {
    const control = action(mode + " · " + modes[mode], () => confirmAction("切换模式", modesCopy[mode],
      () => operate("mode",{mode})), "secondary", state.mode === mode);
    control.setAttribute("aria-pressed", state.mode === mode);
    add(modeSwitch, control);
  }
  const form = node("form", null, "settings-form");
  for (const [key,value] of Object.entries(data.settings)) {
    const input = node("input");
    input.name = key;
    input.type = typeof value === "boolean" ? "checkbox" : "number";
    if (input.type === "checkbox") input.checked = value;
    else { input.min = 1; input.step = 1; input.required = true; input.value = value; }
    add(form, add(node("label"), node("span", labels[key]), input));
  }
  const gpu = data.gpus?.[0];
  const mib = value => value == null ? "不可用" : n(value,0) + " MiB";
  return [add(node("div", null, "resource-grid"),
    stat("CPU 使用率", data.cpu_pct == null ? "不可用" : n(data.cpu_pct,1) + "%"),
    stat("可用内存", mib(data.ram_mb)), stat("磁盘剩余", mib(data.disk_mb)),
    stat("GPU", gpu?.name || "不可用"), stat("GPU 空闲显存", mib(gpu?.free_mb)),
    stat("GPU 温度", gpu?.temperature_c == null ? "不可用" : n(gpu.temperature_c,0) + " °C")),
    card("运行模式", modeSwitch, callout(modesCopy[state.mode]),
      dataList([["电源",data.ac == null ? "不可用" : data.ac ? "交流电源" : "电池"],
        ["用户输入空闲",duration(data.idle_seconds)],
        ["GPU 使用率",gpu?.utilization_pct == null ? "不可用" : n(gpu.utilization_pct,0) + "%"]])),
    card("安全阈值", form, bar(action("保存安全阈值", async () => {
      if (!form.reportValidity()) return;
      const values = Object.fromEntries([...form.elements].map(input => [input.name,
        input.type === "checkbox" ? input.checked : +input.value]));
      await operate("settings", values, "安全阈值已保存。");
    }, ""))),
    card("本地面板", bar(action("关闭面板服务", () => confirmAction("关闭面板服务",
      "此操作关闭 Web 界面。INF1 及其任务保持当前状态。", async () => {
        await operate("close-panel", {}, "面板服务已关闭。");
        el("connection").textContent = "面板已关闭";
        csrf = null;
      }))))];
}

async function loadPage({quiet = false} = {}) {
  const current = page, currentEpoch = ++epoch;
  try {
    const nextState = await api("state");
    let data;
    if (current === "plans") data = await api("plans");
    if (current === "results") data = await api("results");
    if (current === "resources") data = await api("resources");
    if (currentEpoch !== epoch) return;
    state = nextState;
    el("connection").textContent = "本地面板已连接";
    if (quiet && (modal.open || content.contains(document.activeElement))) return;
    const output = ({overview, plans, queue, results, resources:resourcePage})[current](data);
    content.replaceChildren(...output);
  } catch (error) {
    if (currentEpoch !== epoch) return;
    el("connection").textContent = "本地连接有异常";
    if (!quiet) content.replaceChildren(card("暂时无法读取", callout(error.message, "error"),
      bar(action("重新读取", () => loadPage()))));
  }
}
async function navigate(key) {
  page = key;
  el("page-title").textContent = pages[key][0];
  el("page-subtitle").textContent = pages[key][1];
  for (const button of document.querySelectorAll("[data-page]")) {
    if (button.dataset.page === page) button.setAttribute("aria-current","page");
    else button.removeAttribute("aria-current");
  }
  await loadPage();
}
async function connect() {
  const proof = location.hash.slice(1);
  if (proof) history.replaceState(null, "", location.pathname);
  try {
    const session = await api("session", proof ? {proof} : undefined);
    csrf = session.csrf;
    await navigate("overview");
  } catch (error) {
    el("connection").textContent = "尚未授权";
    content.replaceChildren(card("请从 Windows 启动器打开", callout(error.message, "warn")));
  }
}

el("modal-close").addEventListener("click", () => modal.close());
el("refresh").addEventListener("click", () => loadPage());
for (const button of document.querySelectorAll("[data-page]")) {
  button.addEventListener("click", () => navigate(button.dataset.page));
}
setInterval(() => {
  if (csrf && !actionBusy && ["overview","queue"].includes(page)) loadPage({quiet:true});
}, 1800);
connect();
