param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 3001
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = if (Test-Path (Join-Path $scriptRoot ".venv\Scripts\python.exe")) {
    Join-Path $scriptRoot ".venv\Scripts\python.exe"
} else {
    "python"
}

$env:AUTH_HOST = $HostName
$env:AUTH_PORT = "$Port"

Write-Host "Starting mock auth server on http://$HostName`:$Port"
& $pythonExe (Join-Path $scriptRoot "mock_auth_server.py")
