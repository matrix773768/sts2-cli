Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = if ($env:INF1_PYTHON) { $env:INF1_PYTHON } else { 'python.exe' }
Push-Location $repo
try {
    if (!$args.Count) { $args = @('start') }
    & $python -X utf8 -m tools.training_manager @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
