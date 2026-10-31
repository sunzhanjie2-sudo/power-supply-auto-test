param([switch]$SelfTestOnly, [string]$OutputName = 'verification_exe')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskExe = Join-Path $taskRoot 'dist\AutoTestHost.exe'
$taskReports = Join-Path $taskRoot 'test_reports'
New-Item -ItemType Directory -Path $taskReports -Force | Out-Null
$taskLog = Join-Path $taskReports 'exe_selftest.log'
$taskArguments = '--selftest --log-file "' + $taskLog + '"'
$taskProcess = Start-Process -FilePath $taskExe -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
$taskProcess.WaitForExit()
Write-Host ('EXE selftest exit: ' + $taskProcess.ExitCode)
Get-Content -LiteralPath $taskLog -Encoding UTF8 -Tail 4
if ($taskProcess.ExitCode -ne 0) { throw 'Packaged GUI selftest failed' }
if (-not $SelfTestOnly) {
    $taskOutput = Join-Path $taskReports $OutputName
    $taskLog = Join-Path $taskReports 'exe_hardware.log'
    $taskArguments = '--verify-hardware --output "' + $taskOutput + '" --log-file "' + $taskLog + '"'
    $taskProcess = Start-Process -FilePath $taskExe -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
    $taskProcess.WaitForExit()
    Write-Host ('EXE hardware exit: ' + $taskProcess.ExitCode)
    Get-Content -LiteralPath $taskLog -Encoding UTF8 -Tail 7
    $taskSummary = Get-Content -LiteralPath (Join-Path $taskOutput 'verification.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    $taskSummary | Select-Object counts,software_validation,source_off,load_off,image_count,archive_count,archive_matches_csv,viewer_verified,report,success | Format-List
    if (-not $taskSummary.software_validation -or -not $taskSummary.source_off -or -not $taskSummary.load_off) { throw 'Packaged report validation failed' }
}
