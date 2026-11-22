"""中継の hook（relay/hook.js）：入れ方・状態の変わり方・送る回数・秘密を消す・鍵が無ければ何もしない。"""
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "relay" / "hook.js"


def node(js):
    r = subprocess.run(["node", "-e", "const h=require(%s);%s" % (json.dumps(str(HOOK)), js)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


class Relay(unittest.TestCase):
    def test_install_once_and_keeps_other_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "settings.json"
            f.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "node clawd/cloud-hook.js"}]}]}, "model": "x"}))
            for _ in range(2):
                subprocess.run(["node", str(HOOK), "--install", str(f)], check=True, capture_output=True)
            s = json.loads(f.read_text())
            self.assertEqual(s["model"], "x")
            stop = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
            self.assertEqual(sum(".agentboard-relay" in c for c in stop), 1)
            self.assertIn("node clawd/cloud-hook.js", stop)                     # Clawd の hook は残す
            self.assertEqual(s["hooks"]["PreToolUse"][-1]["matcher"], "*")

    def test_states_and_throttle(self):
        out = node("""
const st={};const env={CLAUDE_CODE_REMOTE_SESSION_ID:'session_01Abc'};const P=(e,x)=>Object.assign({hook_event_name:e,session_id:'0123456789ab',cwd:'/home/user/wishlist'},x||{});
const r=[];let t=1000;
r.push(h.step(P('UserPromptSubmit'),st,t,env));
r.push(h.step(P('PreToolUse',{tool_name:'Bash',tool_input:{description:'試験を流す'}}),st,t+=500,env));   // 状態は同じ・3 秒たっていない
r.push(h.step(P('PreToolUse',{tool_name:'Read',tool_input:{file_path:'/a/b/c.py'}}),st,t+=4000,env));
r.push(h.step(P('PreToolUse',{tool_name:'AskUserQuestion'}),st,t+=100,env));
r.push(h.step(P('Stop'),st,t+=100,env));
r.push(h.step(P('PostToolUse'),st,t+=100,env));                                                  // 聞かない hook
console.log(JSON.stringify(r));""")
        self.assertEqual(out[0]["state"], "working")
        self.assertEqual(out[0]["sid"], "01234567")
        self.assertEqual(out[0]["link"], "session_01Abc")
        self.assertEqual(out[0]["project"], "wishlist")
        self.assertIsNone(out[1])                                                # 短い間隔は送らない
        self.assertEqual(out[2]["action"], "読む：b/c.py")
        self.assertEqual(out[2]["tn"], 2)                                        # 送らなかった道具も数える
        self.assertEqual(out[3]["state"], "ask")
        self.assertEqual(out[4]["state"], "yours")
        self.assertIsNone(out[5])

    def test_scrub_secret(self):
        out = node("console.log(JSON.stringify(h.actionOf('Bash',{command:'curl -H x:ghp_abcdefghijklmnopqrstuv mail me@example.com'})))")
        self.assertNotIn("ghp_", out)
        self.assertNotIn("example.com", out)

    def test_no_key_does_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, HOME=d)
            r = subprocess.run(["node", str(HOOK)], input='{"hook_event_name":"Stop","session_id":"x"}', env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0)                                     # 鍵が無ければ読むだけで終わる（送らない）

    def test_install_sh_never_breaks(self):
        t = (ROOT / "relay" / "install.sh").read_text()
        self.assertIn("|| true", t)                                              # 呼ぶ側の書き方も説明に
        self.assertNotIn("set -e", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
