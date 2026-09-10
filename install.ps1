# Install cds-skill into a harness skill root.
#
#   ./install.ps1 -Target dsh-project
#   ./install.ps1 -Target dsh-user
#   ./install.ps1 -Target claude-user
#   ./install.ps1 -Target agents-user
#
# A harness discovers a skill as <root>/<name>/SKILL.md, and the directory name
# must equal the skill name, so this copies the whole bundle to a directory
# literally called cds-skill. The engine resolves config/ and schemas/ relative to
# its own scripts/ directory, so the bundle has to stay intact.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dsh-project', 'dsh-user', 'claude-user', 'agents-user')]
    [string]$Target,

    # Project root for -Target dsh-project. Defaults to the current directory.
    [string]$ProjectRoot = (Get-Location).Path,

    # Copy instead of moving, and overwrite an existing installation.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$SkillName = 'cds-skill'
$Source = $PSScriptRoot

$dshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
$agentsHome = if ($env:DSH_AGENTS_HOME) { $env:DSH_AGENTS_HOME } else { Join-Path $HOME '.agents' }

$destinations = @{
    'dsh-project' = Join-Path $ProjectRoot ".dsh\skills\$SkillName"
    'dsh-user'    = Join-Path $dshHome "skills\$SkillName"
    'claude-user' = Join-Path $HOME ".claude\skills\$SkillName"
    'agents-user' = Join-Path $agentsHome "skills\$SkillName"
}
$destination = $destinations[$Target]

if (-not (Test-Path (Join-Path $Source 'SKILL.md'))) {
    throw "SKILL.md not found beside this script; run the installer from the repository root."
}

if (Test-Path $destination) {
    if (-not $Force) {
        throw "$destination already exists. Re-run with -Force to replace it."
    }
    Remove-Item $destination -Recurse -Force
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null

# Everything the bundle needs at runtime, and nothing it does not.
$include = @('SKILL.md', 'VERSION', 'README.md', 'LICENSE', 'config', 'schemas', 'scripts', 'references', 'examples', 'docs')
foreach ($item in $include) {
    $from = Join-Path $Source $item
    if (Test-Path $from) {
        Copy-Item $from -Destination $destination -Recurse -Force
    }
}

# Strip anything a previous test run left behind.
Get-ChildItem $destination -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

Write-Host "installed  $SkillName -> $destination"
Write-Host ""
Write-Host "Verify with:"
Write-Host "  python `"$destination\scripts\cds.py`" selftest"
Write-Host "  python `"$destination\scripts\cds.py`" run --signals `"$destination\examples\packet_evidence_vs_stance.json`""
