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

# Compatibility launcher; preserve the original declared parameter interface.
& (Join-Path $PSScriptRoot "..\gunnery\agent0\new_codex_worktree.ps1") @PSBoundParameters
