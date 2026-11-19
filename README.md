# agentboard（非公開）

店長の係（PC とクラウド）の様子の置き場。画面は前の PC の AgentBoard と同じ端末風：
https://cxelegy.github.io/Wishlist/board/ （初回だけ、その端末に GitHub の令牌を貼る）

| どこ | 中身 | 書く人 |
|---|---|---|
| 枝 `live-<機械>` の `host.json` | その機械の BRAIN・係（単独の subagent と workflow の回）・道具の出来事・振り分け・Opus・サイト・PC のハーネスの要約 | 集め係 `collect.py`（機械ごとに 1 つ。親なしの 1 コミットを force-push＝履歴が増えない） |
| main の `agents/` | 会話が自分で書く心拍（別のクラウドの会話など） | `ab.py beat` / `end` |
| main の `inbox/` | 店長の伝言 `{t, text, to}` | 画面の `owner $` |
| main の `outbox/` | 返事 `{t, re, text, who}` | BRAIN（`ab.py reply`） |

## 集め係 collect.py

Claude Code の記録（`~/.claude/projects/<作業場所>/<会話>.jsonl`・`<会話>/subagents/agent-*.jsonl`＋`.meta.json`・`subagents/workflows/wf_*/journal.jsonl`）を読む。
前の `server.mjs` の読み取りと同じ考え：係の名前・モデル・道具の回数・かかった時間・いまの動き・状態（作業中／完了／失敗／15 分 記録が増えない＝止まっている）。

- **PC**：`powershell -NoProfile -ExecutionPolicy Bypass -File D:\Claude\agentboard\setup_pc.ps1` を 1 回（ログオンのたびに起こすタスク AgentBoardCollector）。
- **クラウドの会話（主も、主が作る会話も）**：`add_repo cxelegy/agentboard（push）`→ `git clone https://github.com/CxElegy/agentboard /home/user/agentboard` → `python3 /home/user/agentboard/ab.py whoami session_… "会話の名前"`（get_session の id。画面の「開く」）→ `python3 .claude/hooks/agentboard_start.py`（Wishlist の hook。次からは会話の始まりと店長の発言で自動）。
- 店長の許可（2026-11-19）：PC の自動起動タスク・クラウドの主と主が作る会話に agentboard を足す・PC の全部の作業場所の会話を読む。人のいない会話（AI 編集・予約の回）は足さない（許可待ちで止まらないように）。
- 見るだけ：`python collect.py --once --no-push --print`

## 心拍・伝言（ab.py）

```
python ab.py beat <役> <段> "<いま>" [--session session_…] [--model claude-…]
python ab.py end  <役> <段> done
python ab.py inbox                         # 返事のない伝言
python ab.py reply <t> "返事" --who "クラウドの BRAIN"
```

- 秘密は使わない（push は git の認証だけ）。メール・鍵らしい字・ホームのパスは書く前に消す。
- 試験：`python tests/test_ab.py`・`python tests/test_collect.py`
