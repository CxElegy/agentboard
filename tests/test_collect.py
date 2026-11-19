"""collect.py の試験：作り物の ~/.claude/projects で、単独の係・workflow の回・BRAIN・止まり・秘密の消しを確かめ、
使い捨てのリポジトリへ live-<機械> の枝を 1 コミットで push する。python tests/test_collect.py"""
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import collect  # noqa: E402

NOW = 1_800_000_000.0


def iso(t):
    return collect.now_iso(t).replace("+00:00", "Z")


def asst(t, model, tools=(), text=None, stop="tool_use", mid=None, usage=100):
    content = [{"type": "tool_use", "id": f"tu{t}{i}", "name": n, "input": inp} for i, (n, inp) in enumerate(tools)]
    if text:
        content.append({"type": "text", "text": text})
    return {"type": "assistant", "timestamp": iso(t), "message": {"id": mid or f"m{t}", "model": model, "stop_reason": stop, "content": content,
                                                                  "usage": {"input_tokens": usage, "output_tokens": 10}}}


def user_err(t, tu):
    return {"type": "user", "timestamp": iso(t), "message": {"content": [{"type": "tool_result", "tool_use_id": tu, "is_error": True, "content": "Error: timeout 120s"}]}}


def write(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def fake_projects():
    root = pathlib.Path(tempfile.mkdtemp()) / "projects"
    proj = root / "D--Claude"
    sess = "50b60877-aaaa"
    write(proj / f"{sess}.jsonl", [asst(NOW - 30, "claude-fable-5-2", [("TodoWrite", {})])])
    sub = proj / sess / "subagents"
    # 単独の係：終わった（meta.finished）・PR を言った
    write(sub / "agent-a1.jsonl", [asst(NOW - 600, "claude-sonnet-5-5", [("Edit", {"file_path": "/home/someone/Wishlist/scripts/render.py"})]),
                                   asst(NOW - 500, "claude-sonnet-5-5", text="版面の高さを直した。PR #1010 を合併。", stop="end_turn")])
    (sub / "agent-a1.meta.json").write_text(json.dumps({"description": "step:f1", "model": "sonnet", "finished": True}), encoding="utf-8")
    # 単独の係：作業中（記録が 1 分前）・道具がエラー
    write(sub / "agent-a2.jsonl", [asst(NOW - 120, "claude-haiku-5-5", [("Bash", {"command": "curl https://x?k=" + "a" * 40, "description": "本番を開く"})]),
                                   user_err(NOW - 110, f"tu{NOW - 120}0"),
                                   asst(NOW - 60, "claude-haiku-5-5", [("Read", {"file_path": "C:\\Users\\celeg\\x\\y\\z.md"})])])
    (sub / "agent-a2.meta.json").write_text(json.dumps({"description": "check:f1:2 a@b.com"}), encoding="utf-8")
    # workflow の回：1 人は止まっている（20 分 記録なし）、1 人は Opus で終わった
    wf = sub / "workflows" / "wf_313eee3a-1"
    write(wf / "journal.jsonl", [{"type": "started", "agentId": "w1", "label": "fix:T-0001"}, {"type": "started", "agentId": "w2", "label": "diag:T-0001"},
                                 {"type": "completed", "agentId": "w2"}])
    write(wf / "agent-w1.jsonl", [asst(NOW - 1500, "claude-sonnet-5-5", [("Bash", {"command": "gh pr checks"})])])
    write(wf / "agent-w2.jsonl", [asst(NOW - 900, "claude-opus-5-5", text="直すのは高さの決め方で、見た目ではない。", stop="end_turn", usage=5000)])
    # 古い（25 時間前）のは数えない
    old = sub / "agent-old.jsonl"
    write(old, [asst(NOW - 25 * 3600, "claude-haiku-5-5", text="x", stop="end_turn")])
    import os
    os.utime(old, (NOW - 25 * 3600, NOW - 25 * 3600))
    for f in list(proj.rglob("*.jsonl")) + [proj / f"{sess}.jsonl"]:
        if f != old:
            os.utime(f, (NOW - 10, NOW - 10))
    return root


def test_build_reads_agents_runs_brain():
    d = collect.build("pc", fake_projects(), now=NOW)
    by = {a["label"]: a for a in d["agents"]}
    assert set(by) == {"step:f1", "check:f1:2 [x]", "fix:T-0001", "diag:T-0001"}, set(by)
    assert by["step:f1"]["status"] == "done" and by["step:f1"]["pr"] == "1010" and by["step:f1"]["model"] == "Sonnet 5.5"
    assert by["check:f1:2 [x]"]["status"] == "running" and by["check:f1:2 [x]"]["errors"] == 1
    assert by["check:f1:2 [x]"]["action"].startswith("読む：") and "celeg" not in json.dumps(d)
    assert by["fix:T-0001"]["status"] == "stuck"                       # 25 分 記録なし
    assert by["diag:T-0001"]["status"] == "done" and by["diag:T-0001"]["fam"] == "opus"
    assert d["brain"]["model"] == "Fable 5.2" and d["brain"]["active"] is True
    assert d["route"]["run"] == "313eee3a" and d["route"]["status"] == "stopped"
    assert d["opus"]["calls"] == 1 and "高さの決め方" in d["opus"]["recent"][0]["advice"]
    assert d["models"] == {"sonnet": 2, "haiku": 1, "opus": 1}
    assert any(e["err"] and "timeout" in e["text"] for e in d["events"])
    text = json.dumps(d, ensure_ascii=False)
    assert "a" * 40 not in text and "@" not in text                    # 鍵・メールは消える


def test_push_live_one_commit_per_host():
    base = pathlib.Path(tempfile.mkdtemp())
    bare = base / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = base / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    for i in range(3):
        assert collect.push_live(work, "pc", {"at": str(i), "agents": []})
    log = subprocess.run(["git", "-C", str(bare), "log", "--format=%s", "live-pc"], capture_output=True, text=True).stdout.splitlines()
    assert len(log) == 1                                               # 履歴が増えない
    body = subprocess.run(["git", "-C", str(bare), "show", "live-pc:host.json"], capture_output=True, text=True).stdout
    assert json.loads(body)["at"] == "2"


def test_whoami_label_reaches_brain():
    repo = pathlib.Path(tempfile.mkdtemp())
    (repo / ".collector.session.json").write_text(json.dumps({"session": "session_01AbC", "title": "クラウドの主"}), encoding="utf-8")
    d = collect.build("cloud-x", fake_projects(), now=NOW, me=collect.whoami(repo))
    assert d["brain"]["link"] == "session_01AbC" and d["brain"]["name"] == "クラウドの主"
    (repo / ".collector.session.json").write_text(json.dumps({"session": "../evil"}), encoding="utf-8")
    assert collect.whoami(repo)["link"] == ""


def test_fingerprint_ignores_clock():
    a = {"at": "1", "ts": 1, "brain": {"quiet": 1, "model": "x"}, "agents": [{"quiet": 1, "min": 2, "label": "a"}]}
    b = {"at": "2", "ts": 2, "brain": {"quiet": 5, "model": "x"}, "agents": [{"quiet": 3, "min": 4, "label": "a"}]}
    assert collect.fingerprint(a) == collect.fingerprint(b)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("✓", k)
