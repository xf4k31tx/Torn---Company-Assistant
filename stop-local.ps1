$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

docker compose --env-file .env.local --profile development --profile production down
if ($LASTEXITCODE -ne 0) {
    throw "The local application stack did not stop cleanly."
}
Write-Host "Torn Company Assistant stopped. PostgreSQL and Redis data volumes were preserved."
