$pgCtl = 'C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe'
$pgData = "$PSScriptRoot\backend\postgres_data"
& $pgCtl -D $pgData status *> $null
if ($LASTEXITCODE -ne 0) {
    & $pgCtl -D $pgData -l "$PSScriptRoot\.tmp\postgres.log" start
}
$backend = Start-Process python -ArgumentList '-m','uvicorn','app.main:app','--reload','--port','8000' -WorkingDirectory "$PSScriptRoot\backend" -WindowStyle Hidden -PassThru
Write-Host "AMBS demarre : http://localhost:8000"
Write-Host "API : http://localhost:8000/docs"
Write-Host "Processus backend=$($backend.Id)"
