# AgentBoard：店長の PC で 1 回だけ流す（PowerShell）。集め係 collect.py をログオンのたびに起こし、今すぐ 1 つ起こす。
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\Claude\agentboard\setup_pc.ps1
param(
  [string]$Board = "D:\Claude\agentboard",
  [string]$Wishlist = "D:\Claude\Wishlist",
  [string]$State = "D:\Claude\hf\state",
  [string]$Python = "D:\Claude\Wishlist\.venv\Scripts\pythonw.exe"
)
if (-not (Test-Path $Python)) { $Python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
if (-not $Python) { $Python = (Get-Command python.exe).Source }
$targs = "`"$Board\collect.py`" --host pc --loop 30 --wishlist `"$Wishlist`" --summary `"$State\summary.json`" --state `"$State`""
schtasks /Create /F /TN "AgentBoardCollector" /SC ONLOGON /RL LIMITED /TR "`"$Python`" $targs" | Out-Null
schtasks /Run /TN "AgentBoardCollector" | Out-Null
Start-Sleep -Seconds 8
git -C $Board ls-remote origin "refs/heads/live-pc"
Write-Output "AgentBoardCollector を登録して起こしました。上に live-pc の行が出ていれば画面に PC が出ます。"
