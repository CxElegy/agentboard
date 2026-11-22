# agentboard の決まり

- 説明は README.md。返事は日本語。
- ここは公開（2026-11-21 から）。お客さまのデータ・鍵・メールを書かない（ab.py が消すが、手で書くときも）。
- 心拍は ab.py で書く（ファイルを手で直さない）。画面はこのリポジトリの docs/index.html（https://cxelegy.github.io/agentboard/）。
- 店長に設定を頼むとき（Pages・Secrets・令牌・リポジトリの公開など）は、毎回（2026-11-21 店長）：
  1. その設定画面へ直接飛べるリンクを貼る（例 https://github.com/CxElegy/agentboard/settings/pages）。店長に GitHub を開いて探させない。
  2. リンクのすぐ下に「開いたら次に何をするか」を番号付きで書く（どこを押す・何を選ぶ・何を入れる・最後に何を押す・終わったらどうなるか）。
- クラウドの会話を作る（create_session）ときは、環境を必ず「デフォルト」（`env_01LpEFzZemQhvxkfxgxpwfXe`）にする。agentboard・Default・personal-aesthetic の環境は使わない（2026-11-22 店長。中継の hook が setup script で入るのは「デフォルト」）。
