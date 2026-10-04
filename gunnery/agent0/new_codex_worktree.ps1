param(
    [Parameter(Mandatory = $true)]
    [string] $Identity,

    [Parameter(Mandatory = $true)]
    [string] $SourceEnvWorktree,

    [Parameter(Mandatory = $true)]
    [string] $Worktree,

    [Parameter(Mandatory = $true)]
    [string] $Branch,

    [string] $RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$resolvedSource = (Resolve-Path -LiteralPath $SourceEnvWorktree).Path
$targetParent = Split-Path -Path $Worktree -Parent
if (-not $targetParent) {
    throw "Worktree must include a parent path: $Worktree"
}
New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
$resolvedTargetParent = (Resolve-Path -LiteralPath $targetParent).Path
$targetName = Split-Path -Path $Worktree -Leaf
$resolvedTarget = Join-Path $resolvedTargetParent $targetName

if (Test-Path -LiteralPath $resolvedTarget) {
    throw "Target worktree already exists: $resolvedTarget"
}

$envPath = Join-Path $resolvedSource ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing source .env: $envPath"
}

$envMap = @{}
Get-Content -LiteralPath $envPath | Where-Object {
    $_ -match "^[A-Za-z_][A-Za-z0-9_]*="
} | ForEach-Object {
    $key, $value = $_ -split "=", 2
    $envMap[$key] = $value
}

if (-not $envMap.ContainsKey("WEA_AGENT")) {
    throw "Source .env does not define WEA_AGENT"
}

if ($envMap["WEA_AGENT"] -ne $Identity) {
    throw "Source .env WEA_AGENT is '$($envMap["WEA_AGENT"])', expected '$Identity'"
}

$genomePath = Join-Path $resolvedRepoRoot "genomes/$Identity/AGENTS.local.md"
if (-not (Test-Path -LiteralPath $genomePath)) {
    throw "Persistent genome not found for $Identity at $genomePath"
}

$gitRoot = git -C $resolvedRepoRoot rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
    throw "RepoRoot is not a Git repository: $resolvedRepoRoot"
}

git -C $resolvedRepoRoot fetch origin main --prune
if ($LASTEXITCODE -ne 0) {
    throw "git fetch failed"
}

git -C $resolvedRepoRoot worktree add -b $Branch $resolvedTarget origin/main
if ($LASTEXITCODE -ne 0) {
    throw "git worktree add failed"
}

Copy-Item -LiteralPath $envPath -Destination (Join-Path $resolvedTarget ".env")

[pscustomobject]@{
    Identity = $Identity
    Worktree = $resolvedTarget
    Branch = $Branch
    Genome = $genomePath
    EnvCopiedFrom = $envPath
}
