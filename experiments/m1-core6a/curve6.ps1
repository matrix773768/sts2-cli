# Render the confirmation cost frontier with the Windows .NET charting library.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$evidence = Join-Path $PSScriptRoot 'evidence'
$report = Get-Content -LiteralPath (Join-Path $evidence 'results.json') -Raw | ConvertFrom-Json
$stats = $report.stats.confirm
$pairs = $report.comparisons.confirm
$chart = New-Object System.Windows.Forms.DataVisualization.Charting.Chart
$chart.Width = 1150
$chart.Height = 690
$chart.BackColor = 'White'
$area = New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea
$chart.ChartAreas.Add($area)
$area.AxisX.Title = 'End-to-end worker seconds per attempted battle'
$area.AxisY.Title = 'Paired terminal utility relative to H5 tactical32 + V2'
$area.AxisX.Minimum = 0
$area.AxisX.Maximum = [Math]::Ceiling(4*($stats.psobject.Properties | ForEach-Object { $_.Value.per_attempt } | Measure-Object -Maximum).Maximum)/4
$area.AxisX.Interval = 0.25
$area.AxisX.MajorGrid.LineColor = 'Gainsboro'
$area.AxisY.MajorGrid.LineColor = 'Gainsboro'
$area.AxisX.LabelStyle.Format = '0.##;-0.##;0'
$area.AxisY.LabelStyle.Format = '0.#;-0.#;0'
$area.AxisX.TitleFont = New-Object System.Drawing.Font('Segoe UI', 12)
$area.AxisY.TitleFont = $area.AxisX.TitleFont
$legend = New-Object System.Windows.Forms.DataVisualization.Charting.Legend
$legend.Docking = 'Right'
$legend.Font = New-Object System.Drawing.Font('Segoe UI',10)
$chart.Legends.Add($legend)
$null = $chart.Titles.Add('Independent combat: 640 paired worlds per policy, 95% family-bootstrap intervals')
$chart.Titles[0].Font = New-Object System.Drawing.Font('Segoe UI',17)
$names = @{g2='Frozen G2';v2='H5 tactical32 + V2';direct='Direct distilled';clone='Direct behavior clone';low='Guided low';g2low='G2 low';same32='Guided cap 32';same24='Guided cap 24';same48='Guided cap 48';trim32='Guided selective cap 32'}
$palette = @('#274060','#BB431E','#157E66','#7763A8','#2A70A0','#9F721C','#C44B78','#557744')
$index=0
foreach ($prop in $stats.psobject.Properties) {
    $arm = $prop.Name
    $x = [double]$prop.Value.per_attempt
    $d = $pairs.psobject.Properties["$arm minus v2"].Value.utility
    $color = [System.Drawing.ColorTranslator]::FromHtml($palette[$index % $palette.Length])
    $ci = New-Object System.Windows.Forms.DataVisualization.Charting.Series
    $ci.Name = 'interval_' + $arm
    $ci.ChartType = 'Line'
    $ci.IsVisibleInLegend = $false
    $ci.Color = $color
    $ci.BorderWidth=2
    $chart.Series.Add($ci)
    $null=$ci.Points.AddXY($x,[double]$d.ci[0])
    $null=$ci.Points.AddXY($x,[double]$d.ci[1])
    $point = New-Object System.Windows.Forms.DataVisualization.Charting.Series
    $point.Name=$names[$arm]
    $point.ChartType='Point'
    $point.MarkerStyle = if ($arm -in @('g2','clone','direct')) {'Diamond'} else {'Circle'}
    $point.MarkerSize=12
    $point.Color=$color
    $chart.Series.Add($point)
    $null=$point.Points.AddXY($x,[double]$d.mean)
    $index++
}
$chart.SaveImage((Join-Path $evidence 'ability-cost.png'),'Png')
$chart.Dispose()
