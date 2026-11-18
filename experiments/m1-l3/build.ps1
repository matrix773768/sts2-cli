$ErrorActionPreference = 'Stop'
$base = (Resolve-Path CombatSolver-m1-cs1).Path
$source = "$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$copy = (New-Item -ItemType Directory CombatSolver-m1-l3 -Force).FullName
if (Test-Path "$copy/patched-source") { throw 'Use a fresh solver copy' }
$solver = (New-Item -ItemType Directory "$copy/patched-source").FullName
robocopy "$source/src" "$solver/src" /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Source copy failed" }
Copy-Item "$source/CombatSolver.csproj" $solver
Copy-Item "$PSScriptRoot/RankingExperiment.cs" "$solver/src/Search"

function Edit-Copy($File, $Anchor, $Replacement) {
    $path = "$solver/$File"
    $contents = [IO.File]::ReadAllText($path)
    if ([regex]::Matches($contents,[regex]::Escape($Anchor)).Count -ne 1) { throw "Unexpected source in $File" }
    [IO.File]::WriteAllText($path, $contents.Replace($Anchor,$Replacement))
}

Edit-Copy 'CombatSolver.csproj' 'Name="BuildMemoryCleaner" BeforeTargets="Build"' 'Name="BuildMemoryCleaner" BeforeTargets="UnusedOfflineTarget"'
$anchor = '            return bounded;'
Edit-Copy 'src/Search/CombatBeamSolver.Retention.cs' ($anchor + [string][char]10 + '        }' + [string][char]10 + '        finally') ('            ApplyRankingExperiment(bounded);' + [string][char]10 + $anchor + [string][char]10 + '        }' + [string][char]10 + '        finally')
$anchor = '        _run.Expanded++;'
Edit-Copy 'src/Search/CombatBeamSolver.ExpansionPlan.cs' $anchor ($anchor + [string][char]10 + '        ObserveRankingExpansion(node);')
$anchor = '            SolverInterimResult candidate = SummarizeCandidate(node, won: true);'
Edit-Copy 'src/Search/CombatBeamSolver.Phases.cs' $anchor ('            ObserveRankingVictory(node, stopwatch.ElapsedMilliseconds);' + [string][char]10 + $anchor)
$anchor = '                        ended.Add(child);'
Edit-Copy 'src/Search/CombatBeamSolver.Phases.cs' ($anchor + [string][char]10 + '                        acceptableBattleHpLossReached |= MeetsHpTarget(child);') ('                        if (RankingExperiment != null && IsEligibleCompleteVictory(child))' + [string][char]10 + '                            ObserveRankingVictory(child, stopwatch.ElapsedMilliseconds);' + [string][char]10 + $anchor + [string][char]10 + '                        acceptableBattleHpLossReached |= MeetsHpTarget(child);')

$env:DOTNET_CLI_HOME = (Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path sts2-cli/logs/nuget-packages).Path
dotnet build "$solver/CombatSolver.csproj" -c Release -p:CopyModOnBuild=false "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" -p:NuGetAudit=false -o "$copy/bin"
if ($LASTEXITCODE -ne 0) { throw 'Offline solver build failed' }
