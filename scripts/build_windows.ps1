param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",

    [string]$AppName = "nMCP-client"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$distPath = if ($Mode -eq "onefile") { "dist_onefile" } else { "dist_release" }
$workPath = if ($Mode -eq "onefile") { "build_onefile" } else { "build_release" }

$commonArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--windowed",
    "--name", $AppName,
    "--distpath", $distPath,
    "--workpath", $workPath,
    "--add-data", ".private/Candy;.private/Candy"
)

# Optional seed database for memory bootstrap.
if (Test-Path "assets\memory_seed.sqlite") {
    $commonArgs += @("--add-data", "assets/memory_seed.sqlite;assets")
}

if ($Mode -eq "onefile") {
    $commonArgs += "--onefile"
}

$commonArgs += "main.py"

Write-Host "Building $AppName ($Mode)..."
Write-Host "$python $($commonArgs -join ' ')"

& $python @commonArgs

Write-Host "Build complete. Output folder: $distPath"
