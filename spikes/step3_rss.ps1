# Step 3 RSS run: real uvicorn on 127.0.0.1:8010, fresh temp DB, sample scan, searches, new folder.
# Measures the CHILD python.exe (the venv python.exe is a launcher). Usage:
#   powershell -File spikes\step3_rss.ps1 <sample_folder>
param([string]$Sample)
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$db = Join-Path $env:TEMP "st3-rss.db"
Remove-Item "$db*" -ErrorAction SilentlyContinue
$env:VEILFS_DB_PATH = $db
$env:HF_HUB_OFFLINE = "1"
$base = "http://127.0.0.1:8010"
$launcher = Start-Process -FilePath (Join-Path $repo "backend\.venv\Scripts\python.exe") `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010", "--workers", "1" `
  -WorkingDirectory (Join-Path $repo "backend") -PassThru -WindowStyle Hidden
function Child { Get-CimInstance Win32_Process -Filter "ParentProcessId=$($launcher.Id)" | Where-Object Name -eq "python.exe" | Select-Object -First 1 }
function Mem($label) {
  $c = Child; $p = Get-Process -Id $c.ProcessId
  "{0,-34} WS {1,7:N0} MB  PeakWS {2,7:N0} MB  Private {3,7:N0} MB" -f $label, ($p.WorkingSet64/1MB), ($p.PeakWorkingSet64/1MB), ($p.PrivateMemorySize64/1MB)
}
try {
  for ($i = 0; $i -lt 60; $i++) { try { $h = Invoke-RestMethod "$base/health" -TimeoutSec 2; break } catch { Start-Sleep 1 } }
  "health app=$($h.app) launcher=$($launcher.Id) child=$((Child).ProcessId)"
  Mem "idle after /health"
  $t0 = Get-Date
  Invoke-RestMethod "$base/scan" -Method Post -ContentType "application/json" -Body (@{ root = $Sample } | ConvertTo-Json) | Out-Null
  $maxWS = 0; $maxPriv = 0
  do {
    Start-Sleep -Milliseconds 300
    $s = Invoke-RestMethod "$base/scan/status"
    $p = Get-Process -Id (Child).ProcessId
    $maxWS = [Math]::Max($maxWS, $p.WorkingSet64); $maxPriv = [Math]::Max($maxPriv, $p.PrivateMemorySize64)
  } while ($s.state -eq "running")
  $secs = [Math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
  "scan state=$($s.state) took $secs s errors=$($s.errors.Count) stats=" + ($s.stats | ConvertTo-Json -Compress)
  "sampled during scan: max WS {0:N0} MB, max Private {1:N0} MB" -f ($maxWS/1MB), ($maxPriv/1MB)
  Mem "(b) right after the scan"
  $times = @()
  foreach ($q in "money I spent", "invoice", "meeting", "my diary", "volcano penguin") {
    foreach ($k in 1..4) { $t = Measure-Command { $r = Invoke-RestMethod "$base/search?q=$([uri]::EscapeDataString($q))" }; $times += $t.TotalMilliseconds }
    "search '$q': " + (($r.results | ForEach-Object { "$($_.name)=$($_.match)" }) -join ", ")
  }
  $sorted = $times | Sort-Object
  "HTTP searches: n=$($times.Count) median {0:N0} ms max {1:N0} ms" -f $sorted[[int]($sorted.Count/2)], $sorted[-1]
  $f = Invoke-RestMethod "$base/folders" -Method Post -ContentType "application/json" -Body (@{ name = "Bills to pay"; description = "invoices, bills and payments that are due" } | ConvertTo-Json)
  do { Start-Sleep -Milliseconds 300; $s = Invoke-RestMethod "$base/scan/status" } while ($s.state -eq "running")
  "new folder job: $($s.stats | ConvertTo-Json -Compress)"
  $files = Invoke-RestMethod "$base/files?folder_id=$($f.folder_id)"
  "Bills to pay: " + (($files | ForEach-Object name) -join ", ")
  Start-Sleep 2
  Mem "(a) steady: scan+searches+folder"
  $h = Invoke-RestMethod "$base/health"
  "loaded: cactus=$($h.cactus.loaded | ConvertTo-Json -Compress) classifier=$($h.classifier.loaded)"
  (Invoke-RestMethod "$base/files") | ForEach-Object { "  {0,-28} {1}" -f $_.name, (($_.folders | ForEach-Object name) -join ", ") }
} finally {
  & taskkill /PID $launcher.Id /T /F | Out-Null
}
