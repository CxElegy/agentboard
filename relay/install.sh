#!/usr/bin/env bash
# AgentBoard の中継を、この容器に入れる（クラウド環境の setup script から 1 行で呼ぶ）：
#   curl -fsSL https://raw.githubusercontent.com/CxElegy/agentboard/main/relay/install.sh | AB_RELAY_KEY=<鍵> bash || true
# 何度流しても同じ（hook は 1 つだけ）。失敗しても会話の始まりを止めない（呼ぶ側の || true）。
D="$HOME/.agentboard-relay"
mkdir -p "$D" "$HOME/.claude"
curl -fsSL https://raw.githubusercontent.com/CxElegy/agentboard/main/relay/hook.js -o "$D/hook.js.new" && mv "$D/hook.js.new" "$D/hook.js"
if [ -n "${AB_RELAY_KEY:-}" ]; then (umask 077; printf %s "$AB_RELAY_KEY" > "$D/key"); fi
[ -f "$D/hook.js" ] && node "$D/hook.js" --install "$HOME/.claude/settings.json"
