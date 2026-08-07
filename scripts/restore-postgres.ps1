param(
    [Parameter(Mandatory)]
    [string]$BackupPath,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
if (-not $Force) {
    $confirmation = Read-Host "This replaces the local TCA database from '$resolvedBackup'. Type RESTORE to continue"
    if ($confirmation -ne "RESTORE") {
        Write-Host "Restore cancelled."
        exit 0
    }
}

$containerId = docker compose --env-file .env.local ps -q postgres
if (-not $containerId) {
    throw "PostgreSQL is not running. Start the local application first."
}
$containerPath = "/tmp/tca-restore.dump"
docker cp $resolvedBackup "$($containerId):$containerPath"
if ($LASTEXITCODE -ne 0) {
    throw "Could not copy the backup into PostgreSQL."
}
docker compose --env-file .env.local exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner "$1"' -- $containerPath
$restoreCode = $LASTEXITCODE
docker compose --env-file .env.local exec -T postgres rm -f $containerPath
if ($restoreCode -ne 0) {
    throw "PostgreSQL restore failed."
}
Write-Host "Database restored from: $resolvedBackup"
