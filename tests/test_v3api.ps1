[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/api/deep-analysis/v3/analysis" -TimeoutSec 120
    $json = $r.Content | ConvertFrom-Json
    Write-Host "success:" $json.success
    Write-Host "keys:" ($json.PSObject.Properties.Name -join ", ")
    Write-Host "elapsed:" $json.elapsed_seconds
    if ($json.range_analysis) {
        Write-Host "range_analysis keys:" ($json.range_analysis.PSObject.Properties.Name -join ", ")
    }
    if ($json.matrix_data) {
        Write-Host "matrix_data count:" $json.matrix_data.Count
        Write-Host "first item keys:" ($json.matrix_data[0].PSObject.Properties.Name -join ", ")
        Write-Host "first item models keys:" ($json.matrix_data[0].models.PSObject.Properties.Name -join ", ")
    }
} catch {
    Write-Host "ERROR TYPE:" $_.Exception.GetType().FullName
    Write-Host "ERROR MSG:" $_.Exception.Message
}
