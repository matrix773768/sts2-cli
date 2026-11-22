param([Parameter(Mandatory=$true)][string]$GodotDll)
$ErrorActionPreference = 'Stop'
[void][Reflection.Assembly]::LoadFrom((Resolve-Path $GodotDll))
$source = [Godot.GodotObject]::new()
$abi = $source.GetType().GetMethod('Connect', [type[]]@([Godot.StringName],[Godot.Callable],[uint32]))
if ($null -eq $abi -or $abi.ReturnType -ne [Godot.Error]) { throw 'Wrong Connect ABI' }
$global:IIK4BReceived = [Collections.Generic.List[Godot.Node]]::new()
$callback = [Godot.Callable]::new([Action[Godot.Node]]{ param($node) $global:IIK4BReceived.Add($node) })
$signal = [Godot.StringName]::new('hit_creature')
$target = [Godot.Node]::new()
if ($source.Connect($signal, $callback, 0) -ne [Godot.Error]::Ok) {throw 'Connect failed'}
$payload = [Godot.Variant[]]@([Godot.Variant]::new($target))
[void]$source.EmitSignal([Godot.StringName]::new('hit_creature'), $payload)
$source.Disconnect($signal, $callback)
[void]$source.EmitSignal($signal, $payload)
if ($source.Connect($signal, $callback, 4) -ne [Godot.Error]::Ok) {throw 'One-shot connect failed'}
[void]$source.EmitSignal($signal, $payload)
[void]$source.EmitSignal($signal, $payload)
if ($global:IIK4BReceived.Count -ne 2 -or $global:IIK4BReceived[0] -ne $target -or
    $global:IIK4BReceived[1] -ne $target) {throw 'Incorrect signal payload or delivery'}
$parent = [Godot.Node]::new()
[void][Godot.GodotObject].GetMethod("CallDeferred").Invoke($parent, [object[]]@([Godot.Node+MethodName]::AddChild, $payload))
if ($target.GetParent() -ne $parent) {throw 'Deferred AddChild failed'}
'Connect ABI, typed payload, disconnect, one-shot, and deferred AddChild passed'
