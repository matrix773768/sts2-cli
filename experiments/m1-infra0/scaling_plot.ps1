# Render the fixed-work scaling curve with PowerShell on Windows.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
$dir = Join-Path $PSScriptRoot 'evidence/formal'
$rows = Get-Content -Raw -Encoding UTF8 (Join-Path $dir 'summary.json') | ConvertFrom-Json
$baseline = @($rows | Where-Object { $_.kind -eq 'natural' -and $_.arm -eq 'V2' -and $_.mode -eq 'baseline' })
$single = ($baseline | Where-Object n -eq 1 | Measure-Object -Property wall_s -Average).Average
$chart = New-Object System.Windows.Forms.DataVisualization.Charting.Chart
try {
    $chart.Width = 900
    $chart.Height = 450
    $chart.BackColor = [Drawing.Color]::White
    $area = $chart.ChartAreas.Add('plot')
    $area.AxisX.Title = '并发 worker 数'
    $area.AxisX.Minimum = 0.75
    $area.AxisX.Maximum = 4.25
    $area.AxisX.IntervalOffset = 0.25
    $area.AxisX.Interval = 1
    $area.AxisY.Title = '相对单 worker 的吞吐倍率'
    $area.AxisY.Minimum = 0
    $area.AxisY.Maximum = 5
    $area.AxisY.Interval = 1
    $area.AxisX.MajorGrid.Enabled = $false
    $area.AxisY.MajorGrid.LineColor = [Drawing.Color]::Gainsboro
    $legend = $chart.Legends.Add('Legend')
    $legend.Docking = 'Bottom'
    $title = $chart.Titles.Add('5D 高预算 V2：固定 96 场自然战斗')
    $title.Font = [Drawing.Font]::new('Microsoft YaHei',16)
    $font = [Drawing.Font]::new('Microsoft YaHei',10)
    $area.AxisX.TitleFont = $font
    $area.AxisY.TitleFont = $font
    $legend.Font = $font
    $ideal = $chart.Series.Add('理想线性扩展')
    $ideal.ChartType = 'Line'
    $ideal.BorderDashStyle = 'Dash'
    $ideal.Color = [Drawing.Color]::Gray
    $measured = $chart.Series.Add('按两遍平均 wall 计算')
    $measured.ChartType = 'Line'
    $measured.BorderWidth = 3
    $measured.Color = [Drawing.Color]::SteelBlue
    $measured.MarkerStyle = 'Circle'
    $measured.MarkerSize = 8
    $runs = $chart.Series.Add('单遍实测')
    $runs.ChartType = 'Point'
    $runs.MarkerStyle = 'Diamond'
    $runs.MarkerSize = 6
    $runs.Color = [Drawing.Color]::DarkOrange
    foreach ($n in 1,2,4) {
        $group = @($baseline | Where-Object n -eq $n)
        $mean = ($group | Measure-Object -Property wall_s -Average).Average
        $ideal.Points.AddXY($n,$n) | Out-Null
        $point = $measured.Points.AddXY($n,$single/$mean)
        $measured.Points[$point].Label = ('{0:F2}x' -f ($single/$mean))
        foreach ($r in $group) { $runs.Points.AddXY($n,$single/$r.wall_s) | Out-Null }
    }
    $chart.SaveImage((Join-Path $dir 'scaling.png'),'Png')
} finally {
    $chart.Dispose()
}
