param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("data", "data-demo", "train", "run", "test")]
    [string]$Task
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Create it with: py -3.11 -m venv .venv"
}

Push-Location (Join-Path $PSScriptRoot "..")
try {
    switch ($Task) {
        "data" { & $python -m src.wildfire.cli data }
        "data-demo" { & $python -m src.wildfire.cli data-demo }
        "train" { & $python -m src.wildfire.cli train }
        "run" { & $python -m src.wildfire.cli run }
        "test" { & $python -m pytest }
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
