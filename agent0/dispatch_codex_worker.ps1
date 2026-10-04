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

# Compatibility launcher; preserve the original declared parameter interface.
& (Join-Path $PSScriptRoot "..\gunnery\agent0\dispatch_codex_worker.ps1") @PSBoundParameters
