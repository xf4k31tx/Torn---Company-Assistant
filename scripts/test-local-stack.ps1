param(
    [ValidateSet("development", "production")]
    [string]$Profile = "development"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
$port = 8080
$portLine = Get-Content -LiteralPath ".env.local" -ErrorAction SilentlyContinue |
    Where-Object { $_ -match '^TCA_PORT=' } |
    Select-Object -First 1
if ($portLine) {
    $port = [int]($portLine -replace '^TCA_PORT=', '')
}

docker compose --env-file .env.local --profile $Profile ps
$health = Invoke-RestMethod -Uri "http://localhost:$port/api/health" -TimeoutSec 5
$ready = Invoke-RestMethod -Uri "http://localhost:$port/api/ready" -TimeoutSec 5
$homeResponse = Invoke-WebRequest -Uri "http://localhost:$port/" -UseBasicParsing -TimeoutSec 5
if (
    $health.status -ne "ok" -or
    $ready.status -ne "ready" -or
    $homeResponse.StatusCode -ne 200
) {
    throw "One or more local stack checks failed."
}
Write-Host "Local $Profile stack passed proxy, API, PostgreSQL, Redis, and frontend checks."
