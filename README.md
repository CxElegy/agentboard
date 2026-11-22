# agentboard（公開）

店長の係（PC とクラウド）の様子の置き場と、その画面。画面は前の PC の AgentBoard と同じ端末風：
https://cxelegy.github.io/agentboard/ （`docs/index.html`。Pages は main の `/docs`。初回だけ、その端末に GitHub の令牌を貼る）

2026-11-21 に Wishlist（`docs/board/`）から独立させ、リポジトリを公開にした（店長）。`agents/`・`live-*` の中身は誰でも読めるので、お客さまの名前・データ・鍵・メールは書かない。

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

## 中継 relay（クラウドの全部の会話・2026-11-22）

会話ごとに頼まなくても、クラウドの全部の会話の「いま」が画面に出る。`docs/relay/hook.js` が Claude Code の hook として、状態（作業中・あなたの番・質問中）・いまの道具の 1 行・道具の数・係の数・題（最初の頼みの頭 70 字）・モデル・「開く」を、鍵で暗号にして smee.io へ送る。画面は smee.io を直接聞く（1〜2 秒）。git の push も add_repo も token も使わない。

- **新しい会話**：クラウド環境の setup script の最後に 1 行（環境ごとに 1 回。その環境の会話は全部これで入る）：
  `curl -fsSL https://cxelegy.github.io/agentboard/relay/install.sh | AB_RELAY_KEY=<鍵> bash || true`
  網が限られた環境は `cxelegy.github.io` と `smee.io` を許す（入れ口と hook は Pages から配る）。
- **今ある会話**：同じ 1 行をその会話で 1 回流す（容器が作り直されると setup script で自然に入る）。
- **画面**：つながりの行の「鍵を貼る」に同じ鍵（端末ごとに 1 回、localStorage だけ）。
- 送る回数：状態が変わったとき・道具が変わって 3 秒たったとき・45 秒に 1 回。会話の本文・道具の結果は送らない。メール・鍵らしい字は消す。
- 試験：`python tests/test_relay.py`

## 心拍・伝言（ab.py）

```
python ab.py beat <役> <段> "<いま>" [--session session_…] [--model claude-…]
python ab.py end  <役> <段> done
python ab.py inbox                         # 返事のない伝言
python ab.py reply <t> "返事" --who "クラウドの BRAIN"
```

- 秘密は使わない（push は git の認証だけ）。メール・鍵らしい字・ホームのパスは書く前に消す。
- 試験：`python tests/test_ab.py`・`python tests/test_collect.py`・`python tests/test_relay.py`・`python tests/test_page.py`（画面。Playwright があるとき）
