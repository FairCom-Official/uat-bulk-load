#!/usr/bin/env pwsh
# One-command runner for the FairCom vs MariaDB bulk-load benchmark (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File .\run.ps1
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Silence the Docker CLI "What's next:" promotional hints.
$env:DOCKER_CLI_HINTS = 'false'

# Pick a Python launcher (prefer the py launcher on Windows, fall back to python).
$python = if (Get-Command py -ErrorAction SilentlyContinue) { 'py -3' }
          elseif (Get-Command python -ErrorAction SilentlyContinue) { 'python' }
          else { throw 'Python 3 was not found on PATH. Install it from https://www.python.org/downloads/' }

# 1. Config (.env is committed with the project; nothing to create)

# 2. Python dependencies (system Python — no virtualenv)
Invoke-Expression "$python -m pip install --quiet -r requirements.txt"

# 3. Start both databases
Write-Host 'Starting FairCom and MariaDB containers...'
docker compose up -d

# 4. Wait for both to report healthy
Write-Host -NoNewline 'Waiting for containers to become healthy'
foreach ($i in 1..60) {
    $faircom = docker inspect --format='{{.State.Health.Status}}' bulkload-faircom 2>$null
    if (-not $faircom) { $faircom = 'starting' }
    $mariadb = docker inspect --format='{{.State.Health.Status}}' bulkload-mariadb 2>$null
    if (-not $mariadb) { $mariadb = 'starting' }
    if ($faircom -eq 'healthy' -and $mariadb -eq 'healthy') {
        Write-Host ' ok'
        break
    }
    Write-Host -NoNewline '.'
    Start-Sleep -Seconds 2
}

# 5. Run the benchmark (head-to-head result + FairCom REST load diagnostics)
Write-Host 'Running benchmark...'
Invoke-Expression "$python scripts/benchmark.py"

Write-Host ''
Write-Host 'Done. Stop the databases with: docker compose down'
