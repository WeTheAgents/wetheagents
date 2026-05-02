param(
    [Parameter(Mandatory = $true)]
    [string] $Identity,

    [Parameter(Mandatory = $true)]
    [string] $Worktree,

    [string] $GenomeRoot,

    [Parameter(Mandatory = $true)]
    [string] $PromptFile,

    [Parameter(Mandatory = $true)]
    [string] $RunDir,

    [Parameter(Mandatory = $true)]
    [string] $Name,

    [switch] $AllowDirty
)

$ErrorActionPreference = "Stop"

$resolvedWorktree = (Resolve-Path -LiteralPath $Worktree).Path
$resolvedPrompt = (Resolve-Path -LiteralPath $PromptFile).Path
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$resolvedRunDir = (Resolve-Path -LiteralPath $RunDir).Path

if (-not $GenomeRoot) {
    $GenomeRoot = $resolvedWorktree
}
$resolvedGenomeRoot = (Resolve-Path -LiteralPath $GenomeRoot).Path

$envPath = Join-Path $resolvedWorktree ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing worker .env: $envPath"
}

$envMap = @{}
Get-Content -LiteralPath $envPath | Where-Object {
    $_ -match "^[A-Za-z_][A-Za-z0-9_]*="
} | ForEach-Object {
    $key, $value = $_ -split "=", 2
    $envMap[$key] = $value
}

if (-not $envMap.ContainsKey("WEA_AGENT")) {
    throw "Worker .env does not define WEA_AGENT"
}

if ($envMap["WEA_AGENT"] -ne $Identity) {
    throw "Worker .env WEA_AGENT is '$($envMap["WEA_AGENT"])', expected '$Identity'"
}

$genomePath = Join-Path $resolvedGenomeRoot "genomes/$Identity/AGENTS.local.md"
if (-not (Test-Path -LiteralPath $genomePath)) {
    throw "Persistent genome not found for $Identity at $genomePath"
}

$gitRoot = git -C $resolvedWorktree rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
    throw "Worktree is not a Git repository: $resolvedWorktree"
}

if (-not $AllowDirty) {
    $statusErrorPath = [System.IO.Path]::GetTempFileName()
    try {
        $status = git -C $resolvedWorktree status --porcelain 2>$statusErrorPath
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect worktree status: $resolvedWorktree"
        }
        $statusError = Get-Content -LiteralPath $statusErrorPath -Raw
    } finally {
        Remove-Item -LiteralPath $statusErrorPath -Force -ErrorAction SilentlyContinue
    }
    if ($statusError -match "could not open directory|Permission denied|Access is denied") {
        throw "Worktree has inaccessible temp/cache paths. Create a fresh per-task worktree instead: $resolvedWorktree"
    }
    if ($status) {
        throw "Worktree is dirty. Use a clean slot or pass -AllowDirty intentionally.`n$status"
    }
}

$childScript = Join-Path $resolvedRunDir "$($Name)_run.ps1"
$stdoutPath = Join-Path $resolvedRunDir "$($Name).log"
$stderrPath = Join-Path $resolvedRunDir "$($Name).err.log"

$script = @"
`$ErrorActionPreference = "Continue"
Set-Location '$resolvedWorktree'
Get-Content .env | Where-Object { `$_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object {
    `$name, `$value = `$_ -split '=', 2
    [Environment]::SetEnvironmentVariable(`$name, `$value, 'Process')
}
if (-not `$env:GH_TOKEN -and `$env:GITHUB_TOKEN) {
    `$env:GH_TOKEN = `$env:GITHUB_TOKEN
}
Get-Content -Raw '$resolvedPrompt' | codex exec --sandbox danger-full-access -c approval_policy='never' -c shell_environment_policy.inherit='all' -
"@

Set-Content -LiteralPath $childScript -Value $script -Encoding UTF8

$process = Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $childScript) `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

[pscustomobject]@{
    Identity = $Identity
    Worktree = $resolvedWorktree
    Genome = $genomePath
    ProcessId = $process.Id
    Log = $stdoutPath
    ErrorLog = $stderrPath
    Script = $childScript
}
