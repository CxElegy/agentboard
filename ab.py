#!/usr/bin/env python3
"""AgentBoard の書き込み口（PC の係もクラウドの係も同じ道具で書く）。

置き場はこのリポジトリ（非公開）。1 係 1 ファイルなので、何人が同時に書いてもぶつからない。

  python ab.py beat <役> <段> [いま何をしているか] [--where cloud|pc] [--session session_…] [--model claude-…]   係の心拍（同じ中身なら 4 分は push しない）
  python ab.py end  <役> <段> [done|failed|parked]                                       係の終わり
  python ab.py summary <summary.json>         PC の hb.py summary の中身を pc/summary.json へ（PC の見張りが 5 分ごと）
  python ab.py inbox [--json]                 店長の書き込みのうち、まだ返事のないもの
  python ab.py reply <書き込みの t> "返事" [--who 主の会話]
  python ab.py prune [--days 1]               終わってから N 日たった係のファイルを消す

--no-push：書くだけ（試験・まとめて push するとき）。場所は --repo（既定はこのファイルのあるフォルダ）。
秘密は使わない：push は git の認証（クラウドは会話の git、PC は店長の git）だけ。
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
QUIET_PUSH = 240          # 同じ中身の心拍はこの秒数のあいだ push しない（コミットを増やしすぎない）
SECRET = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|eyJ[\w-]{10,}\.[\w-]+\.[\w-]+|(?:ghp|gho|ghs|github_pat|sk|sb)_[\w-]{10,}|\b[A-Fa-f0-9]{40,}\b")


def now_iso(t=None):
    return dt.datetime.fromtimestamp(t if t is not None else time.time(), dt.timezone.utc).isoformat(timespec="seconds")


def scrub(s, n=200):
    return SECRET.sub("[x]", str(s or ""))[:n]


def slug(*parts):
    s = "-".join(str(p) for p in parts if p)
    s = re.sub(r"[^\w.-]+", "_", s, flags=re.UNICODE).strip("_.")
    return s[:80] or "agent"


def guess_where():
    return "cloud" if os.environ.get("CLAUDE_CODE_REMOTE") or os.environ.get("CLAUDE_CODE_REMOTE_SDK_URL") else "pc"


def read(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(p, obj):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def push(repo, paths, msg, tries=4):
    """書いたファイルだけコミットして push。ほかの係と先後したら pull --rebase してやり直す（1 係 1 ファイルなので普通はぶつからない）。"""
    git(repo, "add", "-A", "--", *[str(p) for p in paths])
    if not git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        return "nochange"
    git(repo, "-c", "user.name=agentboard", "-c", "user.email=agentboard@users.noreply.github.com", "commit", "-q", "-m", msg)
    for i in range(tries):
        if git(repo, "push", "-q", "origin", "HEAD:main", check=False).returncode == 0:
            return "pushed"
        git(repo, "pull", "-q", "--rebase", "origin", "main", check=False)
        time.sleep(2 * (i + 1))
    return "failed"


def beat(repo, role, task, note="", where=None, session=None, now=None, status="working", model=None):
    now = now if now is not None else time.time()
    where = where or guess_where()
    old_s = (read(pathlib.Path(repo) / "agents" / (slug(where, role, task) + ".json")) or {}).get("session", "")
    session = session or old_s
    session = session if str(session).startswith("session_") else ""     # 画面の「開く」は claude.ai/code/session_… だけ（会話の中の UUID は網址にならない）
    p = pathlib.Path(repo) / "agents" / (slug(where, role, task) + ".json")
    old = read(p) or {}
    rec = {"id": p.stem, "where": where, "role": scrub(role, 40), "task": scrub(task, 40), "note": scrub(note),
           "status": status, "started": old.get("started") or now_iso(now), "beat": now_iso(now), "ts": now,
           "session": scrub(session, 80), "model": scrub(model or old.get("model") or os.environ.get("ANTHROPIC_MODEL") or "", 40)}
    same = all(old.get(k) == rec[k] for k in ("note", "status", "where", "session")) and now - (old.get("ts") or 0) < QUIET_PUSH
    write(p, rec)
    return p, rec, same


def end(repo, role, task, status="done", where=None, now=None):
    p, rec, _ = beat(repo, role, task, "", where, now=now, status=status)
    return p, rec


def summary(repo, src, now=None):
    s = read(src)
    if s is None:
        raise SystemExit(f"✗ 読めない：{src}")
    s["_pushed"] = now_iso(now)
    p = pathlib.Path(repo) / "pc" / "summary.json"
    write(p, s)
    return p


def _rows(d):
    d = pathlib.Path(d)
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        r = read(f)
        if isinstance(r, dict):
            out.append(r)
    return out


def inbox(repo):
    answered = {str(o.get("re")) for o in _rows(pathlib.Path(repo) / "outbox")}
    return [m for m in sorted(_rows(pathlib.Path(repo) / "inbox"), key=lambda m: str(m.get("t"))) if str(m.get("t")) not in answered]


def reply(repo, re_t, text, who="主の会話", now=None):
    now = now if now is not None else time.time()
    t = int(now * 1000)
    rec = {"t": t, "re": str(re_t), "text": scrub(text, 2000), "who": scrub(who, 40), "at": now_iso(now)}
    p = pathlib.Path(repo) / "outbox" / f"{t}.json"
    write(p, rec)
    return p


def prune(repo, days=1.0, now=None):
    now = now if now is not None else time.time()
    gone = []
    for f in sorted((pathlib.Path(repo) / "agents").glob("*.json")):
        r = read(f) or {}
        if r.get("status") != "working" and now - (r.get("ts") or 0) > days * 86400:
            f.unlink()
            gone.append(f)
    return gone


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(HERE))
    ap.add_argument("--no-push", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("beat"); s.add_argument("role"); s.add_argument("task"); s.add_argument("note", nargs="?", default="")
    s.add_argument("--where", choices=["cloud", "pc"]); s.add_argument("--session", default=""); s.add_argument("--model", default="")
    s = sub.add_parser("end"); s.add_argument("role"); s.add_argument("task"); s.add_argument("status", nargs="?", default="done")
    s.add_argument("--where", choices=["cloud", "pc"])
    s = sub.add_parser("summary"); s.add_argument("src")
    s = sub.add_parser("inbox"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("reply"); s.add_argument("re"); s.add_argument("text"); s.add_argument("--who", default="主の会話")
    s = sub.add_parser("prune"); s.add_argument("--days", type=float, default=1.0)
    a = ap.parse_args(argv)
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(errors="replace")   # Windows の cp932 の画面でも落ちない
        except (AttributeError, ValueError):
            pass
    repo = pathlib.Path(a.repo)
    if a.cmd in ("beat", "end", "summary", "reply", "prune") and not a.no_push:
        git(repo, "pull", "-q", "--rebase", "--autostash", "origin", "main", check=False)
    if a.cmd == "beat":
        p, rec, same = beat(repo, a.role, a.task, a.note, a.where, a.session, model=a.model)
        r = "skip" if (same or a.no_push) else push(repo, [p], f"♥ {rec['where']} {rec['role']} {rec['task']}")
        print(f"♥ {rec['where']} {rec['role']} {rec['task']}（{r}）")
        return 0 if r != "failed" else 1
    if a.cmd == "end":
        p, rec = end(repo, a.role, a.task, a.status, a.where)
        r = "skip" if a.no_push else push(repo, [p], f"■ {rec['where']} {rec['role']} {rec['task']} {a.status}")
        print(f"■ {rec['role']} {rec['task']} {a.status}（{r}）")
        return 0 if r != "failed" else 1
    if a.cmd == "summary":
        p = summary(repo, a.src)
        r = "skip" if a.no_push else push(repo, [p], "PC の要約")
        print(f"✓ pc/summary.json（{r}）")
        return 0 if r != "failed" else 1
    if a.cmd == "inbox":
        if not a.no_push:
            git(repo, "pull", "-q", "--rebase", "--autostash", "origin", "main", check=False)
        rows = inbox(repo)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for m in rows:
                print(f"{m.get('t')}  {m.get('to', '')}  {m.get('text', '')}")
            print(f"返事のない書き込み：{len(rows)}")
        return 0
    if a.cmd == "reply":
        p = reply(repo, a.re, a.text, a.who)
        r = "skip" if a.no_push else push(repo, [p], f"返事 {a.re}")
        print(f"✓ 返事（{r}）")
        return 0 if r != "failed" else 1
    if a.cmd == "prune":
        gone = prune(repo, a.days)
        r = "skip" if (a.no_push or not gone) else push(repo, gone, f"終わった係 {len(gone)} を片づけ")
        print(f"✓ 片づけ {len(gone)}（{r}）")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
