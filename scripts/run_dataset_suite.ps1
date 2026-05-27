param(
    [string]$Site = "mts_internet_online",
    [string]$UrlType = "all",
    [string]$Variant = "all",
    [string]$Form = "all",
    [string]$Pytest = "pytest",
    [string[]]$PytestExtraArgs = @(),
    [string]$Python = "python",
    [bool]$FailOnTestFailures = $true,
    [string]$RunTag = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RunTag)) {
    if ($env:BUILD_NUMBER) {
        $RunTag = "build_$($env:BUILD_NUMBER)"
    } else {
        $RunTag = (Get-Date -Format "yyyyMMdd_HHmmss")
    }
}

$datasets = @(
    @{
        Name = "main_search"
        Tests = @(
            "tests/test_search_variant_a.py::test_search_variant_a",
            "tests/test_search_variant_b.py::test_search_variant_b"
        )
    },
    @{
        Name = "isolation"
        Tests = @(
            "tests/test_search_isolation.py"
        )
    },
    @{
        Name = "adjacent"
        Tests = @(
            "tests/test_adjacent_search.py"
        )
    },
    @{
        Name = "forbidden_region"
        Tests = @(
            "tests/test_forbidden_region.py"
        )
    },
    @{
        Name = "synonyms"
        Tests = @(
            "tests/test_synonyms.py"
        )
    }
)

$failedRuns = @()
$baseDir = "artifacts/allure-results/$Site/datasets/$RunTag"

foreach ($dataset in $datasets) {
    $datasetName = $dataset.Name
    $allureDir = "$baseDir/$datasetName"
    New-Item -ItemType Directory -Path $allureDir -Force | Out-Null

    Write-Host ""
    Write-Host "=== RUN dataset=$datasetName site=$Site run_tag=$RunTag ==="

    $args = @(
        "-q",
        "-s"
    )
    if ($PytestExtraArgs.Count -gt 0) {
        $args += $PytestExtraArgs
    }
    $args += $dataset.Tests
    $args += @(
        "--run-e2e",
        "--site", $Site,
        "--dataset", $datasetName,
        "--url-type", $UrlType,
        "--variant", $Variant,
        "--form", $Form,
        "--alluredir", $allureDir
    )

    & $Pytest @args
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failedRuns += "dataset=$datasetName exit_code=$exitCode"
        Write-Host "RUN FAILED: dataset=$datasetName exit_code=$exitCode"
    }
}

Write-Host ""
Write-Host "Dataset suite run completed. run_tag=$RunTag"

$summaryOut = "artifacts/reports/$Site/datasets/$RunTag/dataset_suite_summary.md"
Write-Host "Building dataset summary -> $summaryOut"
& $Python scripts/summarize_dataset_suite.py `
    --site $Site `
    --run-tag $RunTag `
    --output $summaryOut

$summaryExitCode = $LASTEXITCODE
if ($summaryExitCode -ne 0) {
    Write-Host "Dataset summary build failed with exit code $summaryExitCode"
    exit $summaryExitCode
}

if ($failedRuns.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed dataset runs:"
    $failedRuns | ForEach-Object { Write-Host " - $_" }
    if ($FailOnTestFailures) {
        exit 1
    }
}

exit 0
