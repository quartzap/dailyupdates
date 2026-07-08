param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envTarget = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$secretsTarget = Join-Path $projectRoot ".github-secrets"
$secretsExample = Join-Path $projectRoot ".github-secrets.example"

function Copy-TemplateIfMissing {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    if ((Test-Path -LiteralPath $TargetPath) -and -not $Force) {
        Write-Host "Keeping existing $TargetPath"
        return
    }

    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Force
    Write-Host "Created $TargetPath"
}

Copy-TemplateIfMissing -SourcePath $envExample -TargetPath $envTarget
Copy-TemplateIfMissing -SourcePath $secretsExample -TargetPath $secretsTarget
Write-Host "Next: fill in .env and .github-secrets with your real email settings."
