param(
    [Parameter(Mandatory = $true)][string] $Identity,
    [Parameter(Mandatory = $true)][string] $TaskId,
    [Parameter(Mandatory = $true)][string] $RegistryRoot,
    [Parameter(Mandatory = $true)][string] $Worktree,
    [Parameter(Mandatory = $true)][string] $Branch,
    [Parameter(Mandatory = $true)][string] $PythonExecutable,
    [Parameter(Mandatory = $true)][string] $CodexExecutable,
    [string] $GenomeRoot,
    [Parameter(Mandatory = $true)][string] $PromptFile,
    [Parameter(Mandatory = $true)][string] $RunDir,
    [Parameter(Mandatory = $true)][string] $TaskEvidenceDir,
    [Parameter(Mandatory = $true)][string] $Name,
    [ValidateSet('read-only', 'workspace-write')][string] $Sandbox = 'workspace-write',
    [int] $MaxProcesses = 4,
    [string[]] $Resource = @(),
    [switch] $AllowDirty
)

# Compatibility path uses the same guarded launcher; old incomplete calls fail.
& (Join-Path $PSScriptRoot '../gunnery/agent0/dispatch_codex_worker.ps1') @PSBoundParameters
