param([Parameter(Mandatory)][string]$Output, [int]$Repeats = 5)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$queue = Join-Path $repo 'logs/inf1/queue.sqlite'
$active = python -c "import pathlib,sqlite3,sys; p=pathlib.Path(sys.argv[1]).resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); print(c.execute('select count(*) from runs where ended is null').fetchone()[0])" $queue
if ($LASTEXITCODE -ne 0 -or $active -ne '0') { throw 'INF1 has active runs or its queue is unreadable' }
if (Test-Path -LiteralPath $Output) { throw 'Choose a fresh output directory' }
$out = (New-Item -ItemType Directory -Path $Output).FullName
$build = Get-Content (Join-Path $repo 'logs/hk1a-build/build.json') -Raw | ConvertFrom-Json
$runtime = Join-Path $repo 'logs/m0-v5/dotnet9/dotnet.exe'
$env:DOTNET_PROCESSOR_COUNT = '1'
for ($index = 1; $index -le $Repeats; $index++) {
    $proc = Start-Process -FilePath $runtime -ArgumentList @('"' + $build.dll + '"','--verify-hot-parity','--gate','c') -WorkingDirectory $build.tree -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput "$out/gate-$index.log" -RedirectStandardError "$out/gate-$index.err"
    [pscustomobject]@{ ExitCode = $proc.ExitCode; CpuMs = $proc.TotalProcessorTime.TotalMilliseconds; PeakRss = $proc.PeakWorkingSet64 } |
        ConvertTo-Json | Set-Content -LiteralPath "$out/gate-$index.json"
}
