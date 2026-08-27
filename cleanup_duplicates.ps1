<#
    cleanup_duplicates.ps1
    ----------------------
    Finishes the "consolidate safely" cleanup for the Metamark project:
      * moves deprecated/duplicate backend files into legal_metrology/_archive/
      * removes the stale "extension - Copy" folder (the live one is "extension")

    Uses `git mv` / `git rm` so history is preserved when run inside the repo.
    Falls back to plain filesystem moves/deletes if git isn't available.

    Run from anywhere:
        powershell -ExecutionPolicy Bypass -File .\cleanup_duplicates.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$backend = Join-Path $root 'legal_metrology_backend\legal_metrology'
$archive = Join-Path $backend '_archive'

# Is this a git working tree?
$useGit = $false
try { git rev-parse --is-inside-work-tree *> $null; if ($LASTEXITCODE -eq 0) { $useGit = $true } } catch {}

if (-not (Test-Path $archive)) { New-Item -ItemType Directory -Path $archive | Out-Null }

$files = @('app.py', 'main.py', 'tempCodeRunnerFile.py', 'rag_compliance.py')
foreach ($f in $files) {
    $src = Join-Path $backend $f
    if (Test-Path $src) {
        $dst = Join-Path $archive $f
        Write-Host "Archiving $f ..."
        if ($useGit) {
            git mv -f -- "$src" "$dst" 2>$null
            if ($LASTEXITCODE -ne 0) { Move-Item -Force -- "$src" "$dst" }  # untracked file
        } else {
            Move-Item -Force -- "$src" "$dst"
        }
    } else {
        Write-Host "Skipping $f (not found)"
    }
}

# Remove the duplicate extension folder
$dupExt = Join-Path $root 'extension - Copy'
if (Test-Path $dupExt) {
    Write-Host 'Removing "extension - Copy" ...'
    if ($useGit) {
        git rm -r --quiet -- "$dupExt" 2>$null
        if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force -- "$dupExt" }
    } else {
        Remove-Item -Recurse -Force -- "$dupExt"
    }
} else {
    Write-Host 'Skipping "extension - Copy" (not found)'
}

Write-Host ''
Write-Host 'Done. Review with:  git status'
Write-Host 'Then commit:        git commit -m "chore: archive duplicate/deprecated files"'
