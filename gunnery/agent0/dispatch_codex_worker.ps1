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

$ErrorActionPreference = 'Stop'
$resolvedWorktree = (Resolve-Path -LiteralPath $Worktree).Path
$resolvedPrompt = (Resolve-Path -LiteralPath $PromptFile).Path
$resolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$resolvedCodex = (Resolve-Path -LiteralPath $CodexExecutable).Path
if ([IO.Path]::GetExtension($resolvedCodex) -ne '.exe') {
    throw 'Supply the native codex.exe, not an npm/PowerShell bridge.'
}
if (-not $GenomeRoot) { $GenomeRoot = $resolvedWorktree }
$resolvedGenomeRoot = (Resolve-Path -LiteralPath $GenomeRoot).Path
$genomePath = Join-Path $resolvedGenomeRoot "genomes/$Identity/AGENTS.local.md"
if (-not (Test-Path -LiteralPath $genomePath)) { throw "Missing genome: $genomePath" }
$envPath = Join-Path $resolvedWorktree '.env'
$envMap = @{}
if (Test-Path -LiteralPath $envPath) {
    Get-Content -LiteralPath $envPath | Where-Object {
        $_ -match '^[A-Za-z_][A-Za-z0-9_]*='
    } | ForEach-Object {
        $key, $value = $_ -split '=', 2
        $envMap[$key] = $value
    }
}
$assignedIdentity = $env:WEA_AGENT
if ($envMap.ContainsKey('WEA_AGENT')) { $assignedIdentity = $envMap['WEA_AGENT'] }
if ($assignedIdentity -ne $Identity) { throw 'Session identity disagrees with assignment.' }
$actualRoot = git -C $resolvedWorktree rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or (Resolve-Path -LiteralPath $actualRoot).Path -ne $resolvedWorktree) {
    throw 'Assignment must name the exact Git worktree root.'
}
$actualBranch = git -C $resolvedWorktree branch --show-current
if ($LASTEXITCODE -ne 0 -or $actualBranch -ne $Branch -or $Branch -eq 'main') {
    throw 'Task branch disagrees with actual checkout.'
}
$originUrl = git -C $resolvedWorktree remote get-url origin
if ($LASTEXITCODE -ne 0 -or $originUrl -notmatch '^(https://([^/@]+@)?github\.com/|git@github\.com:)WeTheAgents/wetheagents(\.git)?$') {
    throw 'This launcher requires the canonical WeTheAgents/wetheagents repository.'
}
if (-not $AllowDirty) {
    $status = git -C $resolvedWorktree status --porcelain --untracked-files=all 2>&1
    if ($LASTEXITCODE -ne 0 -or $status) { throw 'Worktree is dirty or cannot be fully inspected.' }
}
if ($Name -notmatch '^[A-Za-z0-9_-]+$') { throw 'Name must be a simple filename stem.' }
if (Test-Path -LiteralPath $RunDir) { throw 'Use a new evidence directory; never overwrite a prior run.' }
New-Item -ItemType Directory -Path $RunDir | Out-Null
$resolvedRunDir = (Resolve-Path -LiteralPath $RunDir).Path
$resolvedRegistry = [IO.Path]::GetFullPath($RegistryRoot)
New-Item -ItemType Directory -Force -Path $TaskEvidenceDir | Out-Null
$resolvedEvidence = (Resolve-Path -LiteralPath $TaskEvidenceDir).Path
$moduleRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$coordinatorFile = Join-Path $moduleRoot 'scripts/task_execution.py'
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $moduleRoot
    $register = @($coordinatorFile, '--root', $resolvedRegistry,
        '--limit', $MaxProcesses, 'register', $TaskId, $Identity, $resolvedWorktree,
        $Branch, '--repository', 'WeTheAgents/wetheagents', '--evidence', $resolvedEvidence)
    if ($Resource.Count) {
        $resourceFile = Join-Path $resolvedRunDir 'resources.json'
        # Keep JSON as literal data; PS5 adds wrappers when reserializing arrays.
        ('[' + ($Resource -join ',') + ']') |
            Set-Content -LiteralPath $resourceFile -Encoding UTF8
        $register += @('--resources-file', $resourceFile)
    }
    $registrationJson = & $resolvedPython @register | Out-String
    if ($LASTEXITCODE -ne 0) { throw 'Coordinator rejected the assignment.' }
    $registration = $registrationJson | ConvertFrom-Json
    $writePaths = @($registration.assignment.resources | Select-Object -Skip 1 |
        ForEach-Object { $_.path })
} finally { $env:PYTHONPATH = $oldPythonPath }

# Fixed script reads JSON data; paths and prompts never become PowerShell code.
$jobPath = Join-Path $resolvedRunDir 'job.json'
$childScript = Join-Path $resolvedRunDir 'supervisor.ps1'
$job = @{
    Identity = $Identity; TaskId = $TaskId; RegistryRoot = $resolvedRegistry
    Worktree = $resolvedWorktree; Branch = $Branch; Genome = $genomePath
    Python = $resolvedPython; Codex = $resolvedCodex; ModuleRoot = $moduleRoot
    CoordinatorFile = $coordinatorFile
    Prompt = $resolvedPrompt; Sandbox = $Sandbox; Limit = $MaxProcesses
    EnvFile = $envPath; RunDir = $resolvedRunDir
    WritePaths = $writePaths
}
$job | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jobPath -Encoding UTF8
@'
$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath $args[0] -Raw | ConvertFrom-Json
Set-Location -LiteralPath $job.Worktree
if (Test-Path -LiteralPath $job.EnvFile) {
    Get-Content -LiteralPath $job.EnvFile | Where-Object {
        $_ -match '^[A-Za-z_][A-Za-z0-9_]*='
    } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}
$env:WEA_AGENT = $job.Identity
$env:PYTHONPATH = $job.ModuleRoot
$code = 1
try {
    $command = @($job.CoordinatorFile, '--root', $job.RegistryRoot,
        '--limit', $job.Limit, 'run', '--stdin-file', $job.Prompt, $job.TaskId,
        '--', $job.Codex, 'exec', '--sandbox', $job.Sandbox, '--json',
        '--output-last-message', (Join-Path $job.RunDir 'result.md'))
    if ($job.WritePaths -and $job.Sandbox -eq 'workspace-write') {
        foreach ($path in $job.WritePaths) { $command += @('--add-dir', $path) }
    }
    $command += '-'
    & $job.Python @command
    $code = $LASTEXITCODE
} finally {
    @{ finished_at = [DateTime]::UtcNow.ToString('o'); exit_code = $code } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job.RunDir 'exit.json') -Encoding UTF8
}
exit $code
'@ | Set-Content -LiteralPath $childScript -Encoding UTF8
$process = Start-Process powershell.exe -WindowStyle Hidden -PassThru `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $childScript + '"'), ('"' + $jobPath + '"')) `
    -RedirectStandardOutput (Join-Path $resolvedRunDir 'events.jsonl') `
    -RedirectStandardError (Join-Path $resolvedRunDir 'stderr.log')
$receipt = [ordered]@{
    TaskId = $TaskId; Identity = $Identity; Worktree = $resolvedWorktree
    Branch = $Branch; RegistryRoot = $resolvedRegistry; ProcessId = $process.Id
    ProcessStartedUtc = $process.StartTime.ToUniversalTime().ToString('o')
    Genome = $genomePath; RunDir = $resolvedRunDir; Script = $childScript
}
$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolvedRunDir 'launch.json') -Encoding UTF8
[pscustomobject] $receipt
