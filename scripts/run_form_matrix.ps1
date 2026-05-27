param(
    [string]$Site = "mts_internet_online",
    [string]$UrlType = "moscow_subdomain",
    [string]$Pytest = "pytest",
    [string]$Python = "python",
    [bool]$FailOnTestFailures = $true
)

$ErrorActionPreference = "Stop"

$forms = @(
    "profit",
    "connection",
    "checkaddress",
    "undecided",
    "moving",
    "express_connection"
)

$variants = @("A", "B")
$failedRuns = @()

foreach ($variant in $variants) {
    foreach ($form in $forms) {
        $allureDir = "artifacts/allure-results/$Site/$UrlType/$variant/$form"
        New-Item -ItemType Directory -Path $allureDir -Force | Out-Null

        Write-Host ""
        Write-Host "=== RUN variant=$variant form=$form site=$Site url_type=$UrlType ==="

        & $Pytest `
            -q -s `
            tests/test_search_variant_a.py::test_search_variant_a `
            tests/test_search_variant_b.py::test_search_variant_b `
            --run-e2e `
            --site $Site `
            --url-type $UrlType `
            --form $form `
            --variant $variant `
            --alluredir $allureDir

        $pytestExitCode = $LASTEXITCODE
        if ($pytestExitCode -ne 0) {
            $failedRuns += "variant=$variant form=$form site=$Site url_type=$UrlType exit_code=$pytestExitCode"
            Write-Host "RUN FAILED: variant=$variant form=$form exit_code=$pytestExitCode"
        }
    }
}

Write-Host ""
Write-Host "Form-matrix run completed."

$summaryOut = "artifacts/reports/$Site/$UrlType/form_matrix_summary.md"
Write-Host "Building summary report -> $summaryOut"
& $Python scripts/summarize_form_matrix.py `
    --site $Site `
    --url-type $UrlType `
    --output $summaryOut

$summaryExitCode = $LASTEXITCODE
if ($summaryExitCode -ne 0) {
    Write-Host "Summary build failed with exit code $summaryExitCode"
    exit $summaryExitCode
}

if ($failedRuns.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed runs:"
    $failedRuns | ForEach-Object { Write-Host " - $_" }
    if ($FailOnTestFailures) {
        exit 1
    }
}

exit 0
