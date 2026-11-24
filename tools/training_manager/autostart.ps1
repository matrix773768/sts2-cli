param(
    [Parameter(Mandatory)]
    [ValidateSet('Register', 'Status', 'Unregister')]
    [string]$Action
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'inf1.ps1'
$name = 'STS2 INF1 Training Manager'
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
switch ($Action) {
    'Register' {
        $python = if ($env:INF1_PYTHON) { $env:INF1_PYTHON } else { (Get-Command python.exe).Source }
        $repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
        $argument = "-X utf8 -m tools.training_manager start --foreground"
        $taskAction = New-ScheduledTaskAction -Execute $python -Argument $argument -WorkingDirectory $repo
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $name -User $account -Action $taskAction -Trigger $trigger -Settings $settings
    }
    'Status' { Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo }
    'Unregister' { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
}
