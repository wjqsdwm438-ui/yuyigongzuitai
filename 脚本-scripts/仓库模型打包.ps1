[CmdletBinding()]
param(
    [string]$Remote,
    [string]$Branch,
    [switch]$Compress
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configPath = Join-Path $projectRoot 'repomix.config.json'
$outputDirectory = Join-Path $projectRoot '导出-exports'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$repomixArguments = @('--yes', 'repomix@1.18.0')
if ($Remote) {
    $repomixArguments += @('--remote', $Remote)
    if ($Branch) {
        $repomixArguments += @('--remote-branch', $Branch)
    }
} else {
    $repomixArguments += $projectRoot
}
$repomixArguments += @('--config', $configPath)
if ($Compress) {
    $repomixArguments += '--compress'
}

Push-Location $projectRoot
try {
    & npx.cmd @repomixArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Repomix 运行失败，退出码：$LASTEXITCODE"
    }
} finally {
    Pop-Location
}
