param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
if (-not $SkipInstall) {
    & $taskPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed' }
}
& $taskPython -m PyInstaller --noconfirm AutoTestHost.spec
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
$taskExe = Join-Path $PSScriptRoot 'dist\AutoTestHost.exe'
if (-not (Test-Path -LiteralPath $taskExe)) { throw 'EXE missing' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $PSScriptRoot 'dist\README.md') -Force
$taskHash = Get-FileHash -LiteralPath $taskExe -Algorithm SHA256
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dist\SHA256.txt') -Value ($taskHash.Hash + '  AutoTestHost.exe') -Encoding utf8
Write-Host "Built: $taskExe"
