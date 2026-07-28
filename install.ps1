$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$marker = "# === reLang setup ==="

$block = @"
$marker (installed by install.ps1)
`$env:Path = "$installDir;`$env:Path"
function relang {
    python "$installDir/relang-submit.py" @args
}
# === end reLang setup ===
"@

$profilePath = $PROFILE
$profileDir = Split-Path -Parent $profilePath
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
}

if (Test-Path $profilePath) {
    $content = Get-Content $profilePath -Raw -ErrorAction Stop
    if ($content -match [regex]::Escape($marker)) {
        Write-Host "Already installed in $profilePath"
        exit 0
    }
}

Add-Content -Path $profilePath -Value "`r`n$block"
Write-Host "Installed in $profilePath"
Write-Host ""
Write-Host "Restart PowerShell or run: . `$PROFILE"
Write-Host "Then use: relang <your-program-command>"
