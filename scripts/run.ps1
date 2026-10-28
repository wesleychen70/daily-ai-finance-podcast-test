param([string]$Command = 'generate')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = Join-Path (Get-Location) '.tools\python'
$env:GH_CONFIG_DIR = Join-Path (Get-Location) '.tools\gh-config'
$pythonPath = 'C:\Users\chenw\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path $pythonPath)) { $pythonPath = 'python' }
& $pythonPath -m podcast $Command
exit $LASTEXITCODE
