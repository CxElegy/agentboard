#!/usr/bin/env python3
"""AgentBoard の集め係（前の PC の server.mjs の読み取りを、PC でもクラウドでも動く形にしたもの）。

主の会話（BRAIN）が動いている機械の上で走らせる。Claude Code の記録を読む：
  ~/.claude/projects/<作業場所>/<会話>.jsonl                         主の会話（BRAIN）
  ~/.claude/projects/<作業場所>/<会話>/subagents/agent-*.jsonl(+.meta.json)   単独の係
  ~/.claude/projects/<作業場所>/<会話>/subagents/workflows/wf_*/journal.jsonl・agent-*.jsonl   workflow の回
＋（あれば）Wishlist の作業ツリー（main の最後・kpi・段の列）と、PC のハーネスの要約 summary.json。

できた 1 枚（host.json）を、このリポジトリの枝 live-<機械> に「1 コミットだけ」で force-push する
（履歴が増えない・PC とクラウドが同じ枝を取り合わない）。画面は live-* の枝を全部読んで合わせる。

  python collect.py --once                       1 回だけ集めて push
  python collect.py --loop 30                    30 秒ごと（中身が変わったときと 5 分ごとだけ push）
  python collect.py --once --no-push --print     見るだけ
  --host pc|cloud-xxxx   --projects DIR   --wishlist DIR   --summary FILE   --repo DIR（既定はこのフォルダ）

秘密は使わない（push は git の認証だけ）。メール・鍵らしい字・ホームのパスは消してから書く。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
STUCK_MIN = 15          # 記録が増えない分 → 止まっている（赤）
RECENT_DONE_H = 2       # これより前に終わった係は「+N 済み」にまとめる
WINDOW_H = 24           # 数える範囲
ACTIVE_MIN = 2          # BRAIN の記録がこの分以内に動いていれば active
HEARTBEAT_S = 300       # 中身が同じでも 5 分ごとに push（画面が「生きている」と分かるように）
SECRET = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|eyJ[\w-]{10,}\.[\w-]+\.[\w-]+|(?:ghp|gho|ghs|ghu|github_pat|sk|sb_secret|sb_publishable|xox[a-z])[-_][\w-]{10,}|\b[A-Fa-f0-9]{40,}\b|[?&](?:k|key|token)=[\w-]{16,}")
HOME_RE = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|/home/[^/\s]+|/Users/[^/\s]+|/root)(?=[\\/])")


def now_iso(t=None):
    return dt.datetime.fromtimestamp(t if t is not None else time.time(), dt.timezone.utc).isoformat(timespec="seconds")


def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def clean(s, n=120):
    s = HOME_RE.sub("~", str(s or ""))
    s = SECRET.sub("[x]", s)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def fam_of(model):
    m = str(model or "").lower()
    for f in ("haiku", "sonnet", "opus", "fable"):
        if f in m:
            return f
    return "other" if m else ""


def model_name(model):
    """claude-sonnet-5-5 → Sonnet 5.5（短い名前は f の頭を大文字に）"""
    m = str(model or "")
    r = re.search(r"(haiku|sonnet|opus|fable)[-_ ]?(\d+)(?:[-_.](\d+))?", m, re.I)
    if r:
        return r.group(1).capitalize() + " " + r.group(2) + ("." + r.group(3) if r.group(3) else "")
    f = fam_of(m)
    return f.capitalize() if f and f != "other" else (m[:20] or "?")


def short_path(p):
    p = HOME_RE.sub("~", str(p or "")).replace("\\", "/")
    parts = [x for x in p.split("/") if x]
    return "/".join(parts[-3:]) if len(parts) > 3 else p


def action_of(name, inp):
    """道具の呼び出し → 画面の 1 行（前の AgentBoard と同じ言い方）"""
    inp = inp if isinstance(inp, dict) else {}
    n = str(name or "")
    if n in ("Bash", "PowerShell"):
        return "コマンド：" + clean(inp.get("description") or inp.get("command"), 90)
    if n in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "書き換える：" + clean(short_path(inp.get("file_path") or inp.get("notebook_path")), 90)
    if n == "Read":
        return "読む：" + clean(short_path(inp.get("file_path")), 90)
    if n in ("Grep", "Glob"):
        return "探す：" + clean(inp.get("pattern"), 90)
    if n == "WebFetch":
        return "ページを開く：" + clean(inp.get("url"), 90)
    if n == "WebSearch":
        return "調べる：" + clean(inp.get("query"), 90)
    if n in ("Agent", "Task"):
        return "任せる：" + clean(inp.get("description") or inp.get("prompt"), 90)
    if n == "Workflow":
        return "workflow を起こす"
    if n.startswith("mcp__"):
        return "道具：" + clean(n.split("__")[-1], 60)
    if n in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "計画を書く"
    return clean(n, 60)


# ---- 記録を読む（変わったファイルだけ読み直す） ----
_CACHE = {}


def read_jsonl(path, tail_bytes=None):
    p = pathlib.Path(path)
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p), tail_bytes)
    c = _CACHE.get(key)
    if c and c[0] == (st.st_mtime, st.st_size):
        return c[1]
    rows = []
    try:
        with open(p, "rb") as f:
            if tail_bytes and st.st_size > tail_bytes:
                f.seek(st.st_size - tail_bytes)
                f.readline()
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        return []
    _CACHE[key] = ((st.st_mtime, st.st_size), rows)
    return rows


def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarize_agent(rows):
    """1 つの記録 → model・道具の回数・token・最初と最後の時刻・いまの動き・結果の 1 行目・道具の出来事"""
    a = {"model": "", "tools": 0, "tok": 0, "t0": None, "t1": None, "action": "", "result": "", "end_turn": False,
         "last_type": "", "events": [], "errors": 0}
    seen = set()
    pending = {}
    for e in rows:
        t = parse_ts(e.get("timestamp"))
        if t:
            a["t0"] = t if a["t0"] is None else min(a["t0"], t)
            a["t1"] = t if a["t1"] is None else max(a["t1"], t)
        ty = e.get("type")
        if ty in ("user", "assistant"):
            a["last_type"] = ty
        m = e.get("message")
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if ty == "assistant":
            a["model"] = m.get("model") or a["model"]
            a["end_turn"] = m.get("stop_reason") == "end_turn"
            if m.get("id") not in seen:
                seen.add(m.get("id"))
                u = m.get("usage") or {}
                a["tok"] += (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            for c in content if isinstance(content, list) else []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    a["tools"] += 1
                    act = action_of(c.get("name"), c.get("input"))
                    a["action"] = act
                    ev = {"t": t, "text": act, "err": False}
                    a["events"].append(ev)
                    pending[c.get("id")] = ev
                elif c.get("type") == "text" and str(c.get("text") or "").strip():
                    first = next((x for x in str(c["text"]).splitlines() if x.strip()), "")
                    a["result"] = clean(first.lstrip("#*> -"), 140)
        elif ty == "user" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                    ev = pending.get(c.get("tool_use_id"))
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                    first = next((x for x in str(body or "").splitlines() if x.strip()), "")
                    a["errors"] += 1
                    if ev is not None:
                        ev["err"] = True
                        ev["text"] = "道具がエラー：" + clean(first, 70)
    a["events"] = a["events"][-12:]
    return a


def status_of(a, now, finished=None, journal_status=None):
    if journal_status in ("failed",):
        return "failed"
    if finished or journal_status == "done":
        return "done"
    if a["end_turn"] and a["last_type"] == "assistant":
        return "done"
    if a["t1"] and now - a["t1"] > STUCK_MIN * 60:
        return "stuck"
    return "running"


PR_RE = re.compile(r"(?:pull/|PR\s*#|#)(\d{3,5})\b")


def agent_record(label, rows, meta, now, source, journal_status=None, run=None):
    a = summarize_agent(rows)
    if not a["t1"]:
        return None
    model = (meta or {}).get("model") if not a["model"] else a["model"]
    st = status_of(a, now, (meta or {}).get("finished"), journal_status)
    pr = PR_RE.search(a["result"] or "")
    return {
        "label": clean(label or (meta or {}).get("description") or (meta or {}).get("agentType") or "agent", 60),
        "model": model_name(model), "fam": fam_of(model) or "other",
        "tools": a["tools"], "tok": a["tok"], "errors": a["errors"],
        "t0": a["t0"], "t1": a["t1"], "min": round(((a["t1"] if st != "running" else now) - a["t0"]) / 60, 1),
        "quiet": round((now - a["t1"]) / 60, 1),
        "action": a["action"], "result": a["result"] if st in ("done", "failed") else "",
        "pr": pr.group(1) if pr and st == "done" else "",
        "status": st, "source": source, "run": run or "",
        "_events": a["events"],
    }


def journal_index(wf):
    """journal.jsonl → {agentId: (label, 状態)}。started 以外の種類は名前で判断（完了・失敗）。"""
    out = {}
    for e in read_jsonl(pathlib.Path(wf) / "journal.jsonl"):
        aid = e.get("agentId") or e.get("agent_id")
        if not aid:
            continue
        ty = str(e.get("type") or "").lower()
        lab, st = out.get(aid, ("", None))
        if ty == "started":
            lab = e.get("label") or lab
        elif any(k in ty for k in ("fail", "error", "cancel", "kill", "abort")):
            st = "failed"
        elif any(k in ty for k in ("complete", "done", "finish", "result", "success", "succeed", "end")):
            st = st or "done"
        out[aid] = (lab or e.get("label") or "", st)
    return out


def scan(projects, now, only=None):
    """記録の場所を全部見て → (brain 候補, 係, workflow の回)。only：見る作業場所の名前（例 D--Claude）だけに絞る"""
    projects = pathlib.Path(projects)
    since = now - WINDOW_H * 3600
    brains, agents, runs = [], [], []
    if not projects.is_dir():
        return brains, agents, runs
    for proj in projects.iterdir():
        if not proj.is_dir() or (only and proj.name not in only):
            continue
        for sess in proj.glob("*.jsonl"):
            try:
                if sess.stat().st_mtime < since:
                    continue
            except OSError:
                continue
            rows = read_jsonl(sess, tail_bytes=400_000)
            a = summarize_agent(rows)
            if a["t1"]:
                title = ""
                for e in reversed(rows):
                    if e.get("type") in ("summary", "custom-title") and (e.get("summary") or e.get("title")):
                        title = e.get("summary") or e.get("title")
                        break
                brains.append({"session": sess.stem[:8], "model": model_name(a["model"]), "fam": fam_of(a["model"]),
                               "t1": a["t1"], "action": a["action"], "title": clean(title, 60), "_events": a["events"][-4:]})
            sub = proj / sess.stem / "subagents"
            if not sub.is_dir():
                continue
            for f in sub.glob("agent-*.jsonl"):
                try:
                    if f.stat().st_mtime < since:
                        continue
                except OSError:
                    continue
                meta = read_json(f.with_suffix(".meta.json")) or read_json(str(f)[:-6] + ".meta.json") or {}
                r = agent_record(meta.get("description"), read_jsonl(f), meta, now, "agent")
                if r:
                    agents.append(r)
            for wf in (sub / "workflows").glob("wf_*") if (sub / "workflows").is_dir() else []:
                try:
                    mt = max((x.stat().st_mtime for x in wf.iterdir()), default=0)
                except OSError:
                    continue
                if mt < since:
                    continue
                idx = journal_index(wf)
                run = wf.name[3:11]
                mine = []
                for f in wf.glob("agent-*.jsonl"):
                    aid = f.stem[len("agent-"):]
                    lab, jst = idx.get(aid, ("", None))
                    r = agent_record(lab or aid[:8], read_jsonl(f), read_json(f.with_suffix(".meta.json")), now, "workflow", jst, run)
                    if r:
                        mine.append(r)
                agents.extend(mine)
                if mine:
                    last = max(mine, key=lambda x: x["t0"] or 0)
                    live = [x for x in mine if x["status"] == "running"]
                    runs.append({"run": run, "t": mt, "stage": last["label"].split(":")[0][:24],
                                 "status": "running" if live else ("stopped" if any(x["status"] in ("stuck", "failed") for x in mine) else "done"),
                                 "agents": len(mine)})
    return brains, agents, runs


# ---- サイト（Wishlist の作業ツリー） ----
def site_info(wishlist, now, state=None):
    if not wishlist:
        return None
    w = pathlib.Path(wishlist)
    out = {}
    try:
        r = subprocess.run(["git", "-C", str(w), "log", "-1", "--format=%h%x09%ct%x09%s", "origin/main"],
                           capture_output=True, text=True, encoding="utf-8", timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            h, ct, s = (r.stdout.strip().split("\t") + ["", ""])[:3]
            out["main"] = {"sha": h, "t": float(ct or 0), "msg": clean(s, 80)}
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    k = read_json(w / "harness" / "kpi" / "latest.json")
    if isinstance(k, dict):
        routes = []
        for route, stages in sorted((k.get("boards") or {}).items()):
            if not isinstance(stages, dict):
                continue
            vals = {s: (v.get("ok") if isinstance(v, dict) else v) for s, v in stages.items()}
            bad = [s for s, v in vals.items() if v is False]
            routes.append({"route": route, "ok": sum(1 for v in vals.values() if v is True), "total": len(vals), "bad": bad[:2]})
        out["kpi"] = {"at": k.get("at"), "routes": routes}
    try:
        sys.path.insert(0, str(w / "harness"))
        import q  # noqa: PLC0415  Wishlist の段の列（harness/q.py）
        tasks = q.load(w, pathlib.Path(state) if state else None)
        c = q.counts(tasks, pathlib.Path(state) if state else None, now)
        nxt = q.ready(tasks, pathlib.Path(state) if state else None, now, owner="*")
        out["backlog"] = {"open": c.get("open", 0), "doing": c.get("claimed", 0), "ask": c.get("waiting", 0),
                          "parked": c.get("parked", 0), "done": c.get("done", 0), "top": clean(nxt[0]["title"], 70) if nxt else ""}
    except Exception:   # noqa: BLE001  列が読めなくても止めない
        pass
    finally:
        if sys.path and sys.path[0] == str(w / "harness"):
            sys.path.pop(0)
    return out or None


def harness_summary(path):
    s = read_json(path) if path else None
    if not isinstance(s, dict):
        return None
    keep = {k: s.get(k) for k in ("at", "queue", "next", "waiting", "parked", "results", "choices", "alerts", "cost") if s.get(k) is not None}
    for a in s.get("agents") or []:
        keep.setdefault("agents", []).append({k: a.get(k) for k in ("role", "task", "note", "quiet", "elapsed", "ts")})
    return json.loads(clean_json(json.dumps(keep, ensure_ascii=False)))


def clean_json(text):
    return SECRET.sub("[x]", HOME_RE.sub("~", text))


# ---- 1 枚にまとめる ----
def build(host, projects, now=None, wishlist=None, summary=None, state=None, only=None):
    now = now or time.time()
    brains, agents, runs = scan(projects, now, only)
    agents.sort(key=lambda a: a["t1"] or 0, reverse=True)
    brain = max(brains, key=lambda b: b["t1"]) if brains else None
    shown, older = [], 0
    for a in agents:
        if a["status"] == "done" and now - (a["t1"] or 0) > RECENT_DONE_H * 3600:
            older += 1
        else:
            shown.append(a)
    events = []
    for a in agents:
        for e in a["_events"]:
            if e["t"] and now - e["t"] < WINDOW_H * 3600:
                events.append({"t": e["t"], "label": a["label"][:22], "fam": a["fam"], "text": e["text"], "err": e["err"]})
    if brain:
        for e in brain["_events"]:
            if e["t"]:
                events.append({"t": e["t"], "label": "BRAIN", "fam": "lead", "text": e["text"], "err": e["err"]})
    events.sort(key=lambda e: e["t"])
    models = {}
    for a in agents:
        models[a["fam"]] = models.get(a["fam"], 0) + 1
    opus = [a for a in agents if a["fam"] == "opus"]
    op = {"calls": len(opus), "tokens": sum(a["tok"] for a in opus), "active": any(a["status"] == "running" for a in opus),
          "recent": [{"label": a["label"], "status": a["status"], "t": a["t1"], "advice": a["result"] or a["action"]} for a in opus[:3]]}
    pending = [{"label": a["label"], "text": a["result"], "pr": a["pr"], "t": a["t1"], "status": a["status"]}
               for a in agents if a["status"] in ("done", "failed") and a["result"] and now - (a["t1"] or 0) < RECENT_DONE_H * 3600][:5]
    route = max(runs, key=lambda r: r["t"]) if runs else None
    out = {
        "v": 1, "host": host, "kind": "pc" if host == "pc" else "cloud", "at": now_iso(now), "ts": now,
        "brain": None if not brain else {k: brain[k] for k in ("session", "model", "fam", "action", "title")} | {
            "quiet": round((now - brain["t1"]) / 60, 1), "active": now - brain["t1"] < ACTIVE_MIN * 60},
        "agents": [{k: v for k, v in a.items() if not k.startswith("_")} for a in shown[:24]],
        "older_done": older + max(0, len(shown) - 24),
        "events": events[-16:], "models": models, "opus": op, "pending": pending,
        "route": route, "runs": runs[:5],
        "site": site_info(wishlist, now, state),
        "harness": harness_summary(summary),
    }
    return json.loads(clean_json(json.dumps(out, ensure_ascii=False)))


# ---- 枝 live-<host> へ 1 コミットだけで push ----
def git(repo, *args, inp=None, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], input=inp, capture_output=True, text=True, encoding="utf-8", check=check)


def push_live(repo, host, data):
    """作業ツリーを触らずに host.json だけの木を作り、親なしのコミットを live-<host> へ force-push。"""
    body = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    blob = git(repo, "hash-object", "-w", "--stdin", inp=body).stdout.strip()
    tree = git(repo, "mktree", inp=f"100644 blob {blob}\thost.json\n").stdout.strip()
    env = dict(os.environ, GIT_AUTHOR_NAME="agentboard", GIT_AUTHOR_EMAIL="agentboard@users.noreply.github.com",
               GIT_COMMITTER_NAME="agentboard", GIT_COMMITTER_EMAIL="agentboard@users.noreply.github.com")
    commit = subprocess.run(["git", "-C", str(repo), "commit-tree", tree, "-m", f"{host} {data.get('at')}"],
                            capture_output=True, text=True, encoding="utf-8", env=env, check=True).stdout.strip()
    for i in range(3):
        r = git(repo, "push", "-q", "-f", "origin", f"{commit}:refs/heads/live-{host}", check=False)
        if r.returncode == 0:
            return True
        time.sleep(3 * (i + 1))
    sys.stderr.write(f"push に失敗：{r.stderr.strip()[:200]}\n")
    return False


def fingerprint(data):
    d = {k: v for k, v in data.items() if k not in ("at", "ts")}
    if d.get("brain"):
        d["brain"] = {k: v for k, v in d["brain"].items() if k != "quiet"}
    d["agents"] = [{k: v for k, v in a.items() if k not in ("quiet", "min")} for a in d.get("agents") or []]
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def default_host():
    if os.environ.get("CLAUDE_CODE_REMOTE") or os.environ.get("CLAUDE_CODE_REMOTE_SDK_URL"):
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.uname().nodename
        return "cloud-" + re.sub(r"[^\w]", "", sid)[:8]
    return "pc"


def default_projects():
    return pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude") / "projects"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default=default_host())
    ap.add_argument("--projects", default=str(default_projects()))
    ap.add_argument("--project", action="append", default=[], help="見る作業場所（~/.claude/projects の下の名前。例 D--Claude）。何度でも。なければ全部")
    ap.add_argument("--wishlist", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--state", default="", help="Wishlist の段の手元の状態（PC は D:/Claude/hf/state）")
    ap.add_argument("--repo", default=str(HERE))
    ap.add_argument("--loop", type=float, default=0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args(argv)
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    host = re.sub(r"[^\w-]", "", a.host)[:24] or "pc"
    last_fp, last_push = None, 0.0
    while True:
        data = build(host, a.projects, None, a.wishlist or None, a.summary or None, a.state or None, set(a.project) or None)
        if a.print:
            print(json.dumps(data, ensure_ascii=False, indent=1))
        fp = fingerprint(data)
        if not a.no_push and (fp != last_fp or time.time() - last_push > HEARTBEAT_S):
            if push_live(a.repo, host, data):
                last_fp, last_push = fp, time.time()
        if a.once or not a.loop:
            return 0
        time.sleep(max(5.0, a.loop))


if __name__ == "__main__":
    sys.exit(main())
