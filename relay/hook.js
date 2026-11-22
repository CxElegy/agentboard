#!/usr/bin/env node
// AgentBoard の中継（relay）：クラウドの会話ごとの「いま」を、暗号にして smee.io へ送る hook。
// 画面（docs/index.html）が smee.io を直接聞いて、会話の札に出す。git の push も add_repo も要らない。
//
//   node hook.js                      Claude Code の hook として（標準入力に hook の JSON）
//   node hook.js --install FILE       FILE（~/.claude/settings.json）に hook を入れる（何度流しても 1 つ）
//
// 鍵：~/.agentboard-relay/key（setup script が AB_RELAY_KEY から書く）。無ければ何もしない。
// 送るもの：会話の id の頭 8 字・「開く」の session_ id・作業場所の名前・題（最初の頼みの頭）・モデル・状態・いまの道具の 1 行・道具の数・係の数。
// メール・鍵らしい字は送る前に消す。会話の本文・道具の結果は送らない。
"use strict";
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const DIR = path.join(os.homedir(), ".agentboard-relay");
const SMEE = "https://smee.io";
const KEEP_MS = 45 * 1000;      // 同じ状態でもこの間隔で 1 回は送る（画面が「届いている」とわかる）
const MIN_MS = 3 * 1000;        // 道具が変わっても、この間隔より短くは送らない
const SECRET = /[\w.+-]+@[\w-]+\.[\w.-]+|eyJ[\w-]{10,}\.[\w-]+\.[\w-]+|(?:ghp|gho|ghs|github_pat|sk|sb)_[\w-]{10,}|\b[A-Fa-f0-9]{40,}\b/g;
const EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUseFailure", "Stop", "SubagentStop", "Notification", "SessionEnd"];
const MATCHER = new Set(["PreToolUse", "PostToolUseFailure"]);

function clean(s, n) { return String(s == null ? "" : s).replace(SECRET, "[x]").replace(/\s+/g, " ").trim().slice(0, n || 90); }
function shortPath(p) { p = String(p || ""); return p.split(/[\\/]/).slice(-2).join("/"); }

// collect.py の action_of と同じ言い方
function actionOf(name, inp) {
  inp = inp && typeof inp === "object" ? inp : {};
  const n = String(name || "");
  if (n === "Bash" || n === "PowerShell") return "コマンド：" + clean(inp.description || inp.command);
  if (["Edit", "Write", "MultiEdit", "NotebookEdit"].includes(n)) return "書き換える：" + clean(shortPath(inp.file_path || inp.notebook_path));
  if (n === "Read") return "読む：" + clean(shortPath(inp.file_path));
  if (n === "Grep" || n === "Glob") return "探す：" + clean(inp.pattern);
  if (n === "WebFetch") return "ページを開く：" + clean(inp.url);
  if (n === "WebSearch") return "調べる：" + clean(inp.query);
  if (n === "Agent" || n === "Task") return "任せる：" + clean(inp.description || inp.prompt);
  if (n === "Workflow") return "workflow を起こす";
  if (n.startsWith("mcp__")) return "道具：" + clean(n.split("__").pop(), 60);
  if (["TodoWrite", "TaskCreate", "TaskUpdate"].includes(n)) return "計画を書く";
  return clean(n, 60);
}

function derive(secret) {
  const h = (label) => crypto.createHash("sha256").update(label + ":" + secret).digest();
  return { topic: "agentboard-" + h("topic").toString("hex").slice(0, 32), key: h("key") };
}

// 形：base64( iv 12 | 暗号文 | tag 16 )（WebCrypto の AES-GCM と同じ並び）
function encrypt(key, obj) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([c.update(JSON.stringify(obj), "utf8"), c.final()]);
  return Buffer.concat([iv, ct, c.getAuthTag()]).toString("base64");
}

// 記録の頭から題（最初の頼み）、尻からモデル
function fromTranscript(file, have) {
  const out = {};
  if (!file) return out;
  let fd;
  try {
    fd = fs.openSync(file, "r");
    const size = fs.fstatSync(fd).size;
    if (!have.title) {
      const b = Buffer.alloc(Math.min(size, 256 * 1024));
      fs.readSync(fd, b, 0, b.length, 0);
      for (const line of b.toString("utf8").split("\n")) {
        let m; try { m = JSON.parse(line); } catch { continue; }
        if (m.type !== "user" || m.isMeta || !m.message) continue;
        let c = m.message.content;
        if (Array.isArray(c)) c = (c.find((x) => x && x.type === "text") || {}).text;
        if (typeof c === "string" && c.trim() && !/^\s*</.test(c)) { out.title = clean(c, 70); break; }
      }
    }
    const n = Math.min(size, 64 * 1024), b = Buffer.alloc(n);
    fs.readSync(fd, b, 0, n, size - n);
    const all = [...b.toString("utf8").matchAll(/"model"\s*:\s*"(claude-[\w.-]+)"/g)];
    if (all.length) out.model = all[all.length - 1][1];
  } catch {} finally { if (fd !== undefined) try { fs.closeSync(fd); } catch {} }
  return out;
}

function modelName(m) {
  const r = /(haiku|sonnet|opus|fable)[-_ ]?(\d+)(?:[-_.](\d+))?/i.exec(String(m || ""));
  return r ? r[1][0].toUpperCase() + r[1].slice(1).toLowerCase() + " " + r[2] + (r[3] ? "." + r[3] : "") : "";
}

function readStdin() {
  return new Promise((resolve) => {
    let buf = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (d) => { buf += d; if (buf.length > 2e6) buf = buf.slice(-2e6); });
    process.stdin.on("end", () => resolve(buf));
    process.stdin.on("error", () => resolve(buf));
  });
}

// 「開く」：クラウドの会話は cse_… を持っている（cse_ → session_ で開ける。collect.py と同じ）
function linkOf(v) { v = String(v || ""); if (v.startsWith("cse_")) v = "session_" + v.slice(4); return /^session_\w+$/.test(v) ? v : ""; }

// 1 回の hook → 送る 1 通（送らないときは null）。st は会話ごとの覚え（ファイルに残す）
function step(p, st, now, env) {
  const ev = p.hook_event_name;
  if (!EVENTS.includes(ev)) return null;
  st.n = st.n || 0; st.tn = st.tn || 0; st.sub = st.sub || 0;
  let state = st.state || "working", err = false;
  if (ev === "SessionStart") { state = "yours"; }
  else if (ev === "UserPromptSubmit") { state = "working"; st.tn = 0; st.turn_t0 = now; st.action = ""; }
  else if (ev === "PreToolUse") {
    state = p.tool_name === "AskUserQuestion" || p.tool_name === "ExitPlanMode" ? "ask" : "working";
    st.n++; st.tn++; st.action = actionOf(p.tool_name, p.tool_input);
    if (p.tool_name === "Agent" || p.tool_name === "Task") st.sub++;
    st.ev = (st.ev || []).concat([{ t: now, text: st.action }]).slice(-8);
  }
  else if (ev === "PostToolUseFailure") { err = true; if (st.ev && st.ev.length) st.ev[st.ev.length - 1].err = true; }
  else if (ev === "SubagentStop") { st.sub = Math.max(0, st.sub - 1); }
  else if (ev === "Notification") { state = "ask"; }
  else if (ev === "Stop") { state = "yours"; st.sub = 0; }
  else if (ev === "SessionEnd") { state = "idle"; st.sub = 0; }
  const changed = state !== st.state || err || ev === "UserPromptSubmit" || ev === "Stop" || ev === "SessionEnd";
  const moved = st.action !== st.sentAction;
  const gap = now - (st.sent || 0);
  st.state = state;
  if (!(changed || (moved && gap >= MIN_MS) || gap >= KEEP_MS)) return null;
  st.sent = now; st.sentAction = st.action;
  return {
    v: 1, t: now, sid: String(p.session_id || "").slice(0, 8), link: linkOf(env.CLAUDE_CODE_REMOTE_SESSION_ID),
    project: clean(p.cwd ? path.basename(String(p.cwd)) : "", 30), title: st.title || "", model: modelName(st.model),
    state, action: st.action || "", n: st.n, tn: st.tn, turn_t0: st.turn_t0 || 0, sub: st.sub, ev: st.ev || [],
  };
}

async function hook() {
  const input = await readStdin();
  let secret = "";
  try { secret = fs.readFileSync(path.join(DIR, "key"), "utf8").trim(); } catch {}
  if (!secret) return;
  let p; try { p = JSON.parse(input); } catch { return; }
  const id = crypto.createHash("sha1").update(String(p.session_id || "x")).digest("hex").slice(0, 12);
  const file = path.join(os.tmpdir(), "agentboard-relay-" + id + ".json");
  let st = {}; try { st = JSON.parse(fs.readFileSync(file, "utf8")); } catch {}
  if (!st.title || !st.model || p.hook_event_name === "Stop") Object.assign(st, fromTranscript(p.transcript_path, st));
  const msg = step(p, st, Date.now(), process.env);
  try { fs.writeFileSync(file, JSON.stringify(st)); } catch {}
  if (!msg) return;
  const { topic, key } = derive(secret);
  const ac = new AbortController(), timer = setTimeout(() => ac.abort(), 2500);
  try {
    await fetch(SMEE + "/" + topic, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ c: encrypt(key, msg) }), signal: ac.signal });
  } catch {} finally { clearTimeout(timer); }
}

function install(file) {
  const command = 'node "' + path.join(DIR, "hook.js") + '"';
  let s = {}; try { s = JSON.parse(fs.readFileSync(file, "utf8")); } catch {}
  s.hooks = s.hooks || {};
  for (const ev of EVENTS) {
    const list = (s.hooks[ev] || []).filter((g) => !(g.hooks || []).some((h) => String(h.command || "").includes(".agentboard-relay")));
    const g = { hooks: [{ type: "command", command, timeout: 5 }] };
    if (MATCHER.has(ev)) g.matcher = "*";
    list.push(g);
    s.hooks[ev] = list;
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(s, null, 2) + "\n");
}

if (require.main === module) {
  if (process.argv[2] === "--install") { install(process.argv[3] || path.join(os.homedir(), ".claude", "settings.json")); console.log("agentboard relay: hook を入れた"); }
  else hook().catch(() => {}).finally(() => process.exit(0));
}
module.exports = { step, actionOf, derive, encrypt, install, clean };
