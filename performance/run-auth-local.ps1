param(
    [string]$BaseUrl = "http://127.0.0.1:3001",
    [int]$Vus = 2,
    [string]$Duration = "30s"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$k6Command = Get-Command k6 -ErrorAction Stop

Write-Host "Running auth k6 test against $BaseUrl"
Write-Host "VUs: $Vus  Duration: $Duration"

& $k6Command.Source run `
    --env "BASE_URL=$BaseUrl" `
    --vus $Vus `
    --duration $Duration `
    (Join-Path $scriptRoot "tests\auth\auth.test.js")
