# agentboard（非公開）

店長の係（PC とクラウド）の様子と、店長 ⇄ 主の会話の書き込みの置き場。
画面：https://cxelegy.github.io/Wishlist/board/ （初回だけ、この端末に GitHub の令牌を貼る）

| フォルダ | 中身 | 書く人 |
|---|---|---|
| `agents/` | 1 係 1 ファイル（どこ・役・段・いま・心拍の時刻・会話の id） | 係（`ab.py beat` / `end`） |
| `pc/summary.json` | PC のハーネスの要約（段の列・結果・案・見張り・重さ・PC の係） | PC の見張り（`watchdog.ps1` → `ab.py summary`） |
| `inbox/` | 店長の書き込み `{t, text, to}` | 画面の「送る」 |
| `outbox/` | 返事 `{t, re, text, who}` | 主の会話（`ab.py reply`） |

## 係の書き方

```
python ab.py beat <役> <段> "<いま何をしているか>"     # 心拍（同じ中身なら 4 分は push しない）
python ab.py end  <役> <段> done                         # 終わり（failed / parked も）
python ab.py inbox                                       # 返事のない店長の書き込み
python ab.py reply <t> "返事" --who "クラウドの主"
python ab.py prune --days 1                              # 終わって 1 日たった係を片づけ
```

- クラウドの会話：`add_repo cxelegy/agentboard（push）` → `git clone https://github.com/CxElegy/agentboard /home/user/agentboard`。
- PC：`git clone https://github.com/CxElegy/agentboard D:\Claude\agentboard`（見張りがここを探す）。
- クラウドの会話は最初の心拍に `--session session_…`（get_session で分かる自分の id）を付けると、画面に「開く」が出る（2 回目からは覚えている）。
- 秘密は使わない（push は git の認証だけ）。メール・鍵らしい字は書く前に消す。
- 試験：`python tests/test_ab.py`
