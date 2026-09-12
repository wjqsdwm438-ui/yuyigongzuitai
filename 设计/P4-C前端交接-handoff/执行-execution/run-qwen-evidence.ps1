$ErrorActionPreference = 'Stop'
$p4Root = $PSScriptRoot
$p4ReceiptPath = Join-Path $p4Root 'qwen-run-receipt.json'
if (Test-Path -LiteralPath $p4ReceiptPath) { throw 'dispatch-02 already attempted; no implicit retry' }
$p4Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'C:\Users\admin\.codex\tools\qwen3-asr-batch.ps1', '-InputPath', (Join-Path $p4Root '独立核验-inputs'), '-OutDir', (Join-Path $p4Root '独立核验-qwen'), '-Backend', 'transformers', '-RequireCuda')
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:MODELSCOPE_OFFLINE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
foreach ($p4Name in @('HF_HOME','TORCH_HOME','NUMBA_CACHE_DIR','TEMP','TMP','TMPDIR')) {
    $p4Cache = Join-Path $p4Root ('cache/' + $p4Name.ToLowerInvariant())
    New-Item -ItemType Directory -Force -Path $p4Cache | Out-Null
    [Environment]::SetEnvironmentVariable($p4Name, $p4Cache, 'Process')
}
$p4Record = [ordered]@{ status='starting'; started_at=(Get-Date -Format o); model_process_limit=1; new_tts_calls=0; timeout_seconds=600; wrapper='C:/Users/admin/.codex/tools/qwen3-asr-batch.ps1'; arguments=$p4Args; exit_code=$null }
$p4Record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $p4ReceiptPath -Encoding UTF8
$p4Process = Start-Process -FilePath 'powershell.exe' -ArgumentList $p4Args -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $p4Root 'qwen-stdout.log') -RedirectStandardError (Join-Path $p4Root 'qwen-stderr.log')
$p4Handle = $p4Process.Handle
$p4Record.wrapper_pid = $p4Process.Id
$p4Record.status = 'running'
$p4Record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $p4ReceiptPath -Encoding UTF8
$p4Timer = [Diagnostics.Stopwatch]::StartNew()
while (-not $p4Process.WaitForExit(1000)) {
    if ($p4Timer.Elapsed.TotalSeconds -ge 600) {
        & taskkill.exe /PID $p4Process.Id /T /F | Out-File -LiteralPath (Join-Path $p4Root 'qwen-timeout.log') -Encoding UTF8
        $p4Record.status = 'operator_timeout'
        break
    }
}
$p4Process.WaitForExit()
if ($null -eq $p4Process.ExitCode) { throw 'wrapper exit code unavailable; cannot claim successful completion' }
$p4Record.exit_code = $p4Process.ExitCode
$p4Record.elapsed_seconds = [Math]::Round($p4Timer.Elapsed.TotalSeconds, 3)
if ($p4Record.status -eq 'running') { $p4Record.status = if ($p4Process.ExitCode -eq 0) { 'completed' } else { 'failed' } }
$p4Record.finished_at = Get-Date -Format o
$p4Record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $p4ReceiptPath -Encoding UTF8
if ($p4Record.status -eq 'operator_timeout') { exit 3 }
exit $p4Process.ExitCode
