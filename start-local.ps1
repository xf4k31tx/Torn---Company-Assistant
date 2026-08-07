param(
    [ValidateSet("development", "production")]
    [string]$Profile = "development",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Install or start Docker Desktop, then run this launcher again."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its engine is not running."
}

if (-not (Test-Path -LiteralPath ".env.local")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env.local"
    Write-Host "Created local .env.local from .env.example."
}

Write-Host "Starting Torn Company Assistant ($Profile profile)..."
docker compose --env-file .env.local --profile $Profile up -d --build --wait
if ($LASTEXITCODE -ne 0) {
    throw "The local application stack did not start successfully."
}

$port = 8080
$portLine = Get-Content -LiteralPath ".env.local" |
    Where-Object { $_ -match '^TCA_PORT=' } |
    Select-Object -First 1
if ($portLine) {
    $port = [int]($portLine -replace '^TCA_PORT=', '')
}
$url = "http://localhost:$port"
$deadline = (Get-Date).AddMinutes(2)
do {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

if ((Get-Date) -ge $deadline) {
    docker compose --env-file .env.local --profile $Profile ps
    throw "Containers started, but the application did not become reachable at $url."
}

Write-Host "Torn Company Assistant is ready at $url"
docker compose --env-file .env.local --profile $Profile ps
if (-not $NoBrowser) {
    Start-Process $url
}
