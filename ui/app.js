// 前端逻辑：连接 /ws，渲染事件流，支持文件树预览与中断。

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const terminal = $("terminal");
const tree = $("tree");
const status = $("status");
const taskInput = $("task");
const sendBtn = $("send");
const stopBtn = $("stop");

let ws = null;
let running = false;

function setStatus(text, cls) {
  status.textContent = text;
  status.className = cls || "";
}

function scrollDown(el) {
  el.scrollTop = el.scrollHeight;
}

function appendChat(cls, html) {
  const div = document.createElement("div");
  div.className = "ev " + cls;
  div.innerHTML = html;
  chat.appendChild(div);
  scrollDown(chat);
}

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// ---- WebSocket ----
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => setStatus("已连接", "ok");
  ws.onclose = () => { setStatus("已断开", "bad"); running = false; setButtons(); };
  ws.onerror = () => setStatus("连接错误", "bad");
  ws.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

function setButtons() {
  sendBtn.disabled = running;
  stopBtn.disabled = !running;
}

function handleEvent(ev) {
  switch (ev.type) {
    case "system":
      appendChat("system", esc(ev.text));
      break;
    case "step":
      appendChat("step", `—— 第 ${ev.step} 步 ——`);
      break;
    case "message":
      appendChat("msg", esc(ev.content));
      break;
    case "action": {
      const badge = ev.source.startsWith("mcp")
        ? `<span class="badge mcp">MCP</span>`
        : `<span class="badge builtin">内置</span>`;
      const args = esc(JSON.stringify(ev.args, null, 2));
      appendChat("action", `🔧 <b>${esc(ev.tool)}</b>${badge}<br><code>${args}</code>`);
      break;
    }
    case "observation":
      appendChat("obs" + (ev.is_error ? " err" : ""), `↳ ${esc(ev.tool)}：\n${esc(ev.content)}`);
      if (ev.tool === "bash") appendTerminal(ev.content);
      break;
    case "final":
      appendChat("final", "✅ 完成：\n" + esc(ev.content));
      finish();
      break;
    case "interrupted":
      appendChat("note", "⛔ " + esc(ev.text));
      finish();
      break;
    case "max_steps":
      appendChat("note", "⏱ " + esc(ev.text));
      finish();
      break;
    case "error":
      appendChat("obs err", "💥 " + esc(ev.text));
      finish();
      break;
    case "done":
      finish();
      break;
  }
}

function finish() {
  running = false;
  setButtons();
}

function appendTerminal(content) {
  const div = document.createElement("div");
  div.className = "term-line";
  div.innerHTML = `<div class="out">${esc(content)}</div>`;
  terminal.appendChild(div);
  scrollDown(terminal);
}

// ---- 发送 / 中断 ----
sendBtn.onclick = () => {
  const task = taskInput.value.trim();
  if (!task || !ws || ws.readyState !== 1) return;
  chat.innerHTML = "";
  terminal.innerHTML = "";
  running = true;
  setButtons();
  ws.send(JSON.stringify({ type: "run", task }));
};

stopBtn.onclick = () => {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "interrupt" }));
};

taskInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !running) sendBtn.click();
});

// ---- 文件树 ----
async function loadTree() {
  const res = await fetch("/api/tree");
  const data = await res.json();
  tree.innerHTML = "";
  tree.appendChild(renderNode({ name: "workspace/", path: "", type: "dir", children: data.children }, true));
}

function renderNode(node, open) {
  const wrap = document.createElement("div");
  const item = document.createElement("div");
  item.className = "tree-item " + (node.type === "dir" ? "tree-dir" : "tree-file");
  item.textContent = node.name;
  wrap.appendChild(item);

  if (node.type === "dir") {
    const kids = document.createElement("div");
    kids.className = "tree-children";
    (node.children || []).forEach((c) => kids.appendChild(renderNode(c, false)));
    if (!open) kids.style.display = "none";
    item.onclick = () => { kids.style.display = kids.style.display === "none" ? "block" : "none"; };
    wrap.appendChild(kids);
  } else {
    item.onclick = () => previewFile(node.path);
  }
  return wrap;
}

async function previewFile(path) {
  const res = await fetch("/api/file?path=" + encodeURIComponent(path));
  const data = await res.json();
  const box = $("preview");
  box.classList.add("on");
  if (data.type === "text") {
    box.innerHTML = `<div class="phead">${esc(path)}</div><pre>${esc(data.content)}</pre>`;
  } else if (data.type === "image") {
    box.innerHTML = `<div class="phead">${esc(path)}（图片，此处不渲染缩略图）</div>`;
  } else {
    box.innerHTML = `<div class="phead err">${esc(data.content)}</div>`;
  }
}

// 启动
connect();
loadTree();
setInterval(() => { if (!ws || ws.readyState > 1) connect(); }, 3000);
