param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot "backups"
}
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

$containerId = docker compose --env-file .env.local ps -q postgres
if (-not $containerId) {
    throw "PostgreSQL is not running. Start the local application first."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $resolvedOutput "tca-postgres-$stamp.dump"
$containerPath = "/tmp/tca-postgres-$stamp.dump"

docker compose --env-file .env.local exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file="$1"' -- $containerPath
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL backup creation failed."
}
docker cp "$($containerId):$containerPath" $backupPath
docker compose --env-file .env.local exec -T postgres rm -f $containerPath

if (-not (Test-Path -LiteralPath $backupPath)) {
    throw "The backup file was not copied to the host."
}
Write-Host "Backup created: $backupPath"
