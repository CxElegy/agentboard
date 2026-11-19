"""ab.py の試験（git を使わない部分と、使い捨てのリポジトリへの push）。python -m pytest tests または python tests/test_ab.py"""
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ab  # noqa: E402


def _tmp():
    return pathlib.Path(tempfile.mkdtemp())


def test_beat_one_file_per_agent_and_keeps_started():
    r = _tmp()
    p1, a, same = ab.beat(r, "作る", "T-1", "試験", where="cloud", session="s1", now=1000)
    assert not same and a["started"] == ab.now_iso(1000)
    p2, b, same = ab.beat(r, "作る", "T-1", "試験", where="cloud", now=1100)
    assert p1 == p2 and same and b["started"] == a["started"]       # 同じ中身・4 分以内 → push しない
    _, _, same = ab.beat(r, "作る", "T-1", "別のこと", where="cloud", now=1110)
    assert not same
    ab.beat(r, "審査", "T-1", where="pc", now=1000)
    assert len(list((r / "agents").glob("*.json"))) == 2


def test_scrub_hides_mail_and_tokens():
    r = _tmp()
    _, a, _ = ab.beat(r, "x", "y", "a@b.com ghp_abcdefghijklmnop " + "f" * 64, where="pc", now=1)
    assert "@" not in a["note"] and "ghp_" not in a["note"] and "f" * 64 not in a["note"]


def test_end_and_prune():
    r = _tmp()
    ab.beat(r, "作る", "T-2", where="pc", now=0)
    _, rec = ab.end(r, "作る", "T-2", "done", where="pc", now=10)
    assert rec["status"] == "done"
    ab.beat(r, "作る", "T-3", where="pc", now=0)                       # 動いている係は消さない
    gone = ab.prune(r, days=1, now=10 + 2 * 86400)
    assert [g.name for g in gone] == ["pc-作る-T-2.json"]


def test_inbox_reply():
    r = _tmp()
    (r / "inbox").mkdir()
    for t, txt in ((1, "一"), (2, "二")):
        (r / "inbox" / f"{t}.json").write_text(json.dumps({"t": t, "text": txt}), encoding="utf-8")
    assert [m["t"] for m in ab.inbox(r)] == [1, 2]
    ab.reply(r, 1, "了解", now=5)
    assert [m["t"] for m in ab.inbox(r)] == [2]


def test_push_to_bare_repo():
    base = _tmp()
    bare = base / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = base / "w"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    p, rec, _ = ab.beat(work, "主の会話", "brain", "試し", where="cloud", now=1)
    assert ab.push(work, [p], "♥") == "pushed"
    assert ab.push(work, [p], "♥") == "nochange"
    log = subprocess.run(["git", "-C", str(bare), "log", "--format=%s", "main"], capture_output=True, text=True).stdout
    assert "♥" in log


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("✓", k)
