# Prototype: sustained llama.cpp load test with telemetry and an 85 C stop.
$ProgressPreference = 'SilentlyContinue'
$bin = 'C:\gpudoc\tools\llama.cpp\b12177-vulkan\bin'
$model = 'C:\gpudoc\models\qwen2.5-7b-q4_k_m\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf'
$run = 'C:\gpudoc\runs\2026-11-06_gtx1660_llama_vulkan_15min_' + (Get-Date -Format HHmmss)
New-Item -ItemType Directory -Force -Path $run | Out-Null
$q = 'temperature.gpu,fan.speed,power.draw,utilization.gpu,memory.used,pstate,clocks_event_reasons.hw_thermal_slowdown,clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.sw_power_cap'
$drv0 = (nvidia-smi --query-gpu=name,driver_version,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader)
'=== before: ' + $drv0
$start = Get-Date
'=== start ' + $start.ToString('s')
"elapsed_s,iteration,$q" | Set-Content "$run\telemetry.csv"
$limit = 900; $iter = 0; $end = 'time limit reached'; $max = 0; $maxmem = 0; $n = 0
while (((Get-Date) - $start).TotalSeconds -lt $limit) {
  $iter++
  $a = @('-m', "`"$model`"", '-ngl', '99', '-p', '512', '-n', '256', '-r', '3', '-o', 'jsonl')
  $p = Start-Process -FilePath "$bin\llama-bench.exe" -ArgumentList $a -WorkingDirectory $bin -NoNewWindow -PassThru -RedirectStandardOutput "$run\bench_$iter.jsonl" -RedirectStandardError "$run\bench_$iter.err.txt"
  $handle = $p.Handle
  while (-not $p.HasExited) {
    Start-Sleep -Seconds 10; $n++
    $el = [int]((Get-Date) - $start).TotalSeconds
    $s = nvidia-smi --query-gpu=$q --format=csv,noheader 2>&1
    "$el,$iter,$s" | Add-Content "$run\telemetry.csv"
    if ($n % 18 -eq 0) { "t=${el}s iter=$iter  $s" }
    $parts = $s -split ','
    $t = 0
    if (-not [int]::TryParse($parts[0].Trim(), [ref]$t)) { $end = "sensor read failed: $s"; break }
    if ($t -gt $max) { $max = $t }
    $m = [int](($parts[4] -replace '[^0-9]', '')); if ($m -gt $maxmem) { $maxmem = $m }
    if ($t -ge 85) { $end = 'ABORT at 85 C'; break }
    if ($el -ge ($limit + 240)) { $end = 'hard time limit'; break }
  }
  if ($end -ne 'time limit reached') { break }
  $p.WaitForExit()
  if ($p.ExitCode -ne 0) { $end = "llama-bench exited with code $($p.ExitCode) on iteration $iter"; break }
}
"=== end reason: $end"
"=== iterations started: $iter, samples: $n, max temp: $max C, max VRAM: $maxmem MiB"
Get-Process llama-bench* -ErrorAction SilentlyContinue | Stop-Process -Force
for ($w = 0; $w -lt 20 -and @(Get-Process llama-bench* -ErrorAction SilentlyContinue).Count -gt 0; $w++) { Start-Sleep -Seconds 1 }
'=== remaining processes: ' + @(Get-Process llama-bench* -ErrorAction SilentlyContinue).Count
Start-Sleep -Seconds 5
$drv1 = (nvidia-smi --query-gpu=name,driver_version,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader)
'=== after: ' + $drv1
'=== driver unchanged: ' + (($drv0 -split ',')[1].Trim() -eq ($drv1 -split ',')[1].Trim())
'=== now: ' + (nvidia-smi --query-gpu=temperature.gpu,fan.speed,power.draw,utilization.gpu,memory.used --format=csv,noheader)
'=== sw thermal samples: ' + @(Select-String -Path "$run\telemetry.csv" -Pattern 'Not Active, Active, ').Count + ' of ' + $n
'=== driver errors since start: ' + (Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='nvlddmkm';StartTime=$start} -ErrorAction SilentlyContinue | Measure-Object).Count
'=== speed results'
$rows = Get-ChildItem "$run\bench_*.jsonl" | ForEach-Object { Get-Content $_.FullName } | Where-Object { $_ -match '^\{' } | ForEach-Object { $_ | ConvertFrom-Json }
foreach ($r in $rows) { "prompt_tokens={0} gen_tokens={1} avg_ts={2:N2} stddev={3:N2} backend={4} n_ctx={5} gpu_layers={6}" -f $r.n_prompt, $r.n_gen, $r.avg_ts, $r.stddev_ts, $r.backends, $r.n_ctx, $r.n_gpu_layers }
'=== last stderr lines'
Get-ChildItem "$run\bench_*.err.txt" | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Get-Content $_.FullName -Tail 10 }
'=== run folder: ' + $run
