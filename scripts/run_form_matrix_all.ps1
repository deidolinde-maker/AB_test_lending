param(
    [string]$Site = "mts_internet_online",
    [string]$Pytest = "pytest",
    [string]$Python = "python",
    [bool]$FailOnTestFailures = $true
)

$ErrorActionPreference = "Stop"

$urlTypes = @(
    "domain_without_region",
    "moscow_subdomain",
    "balashikha_folder",
    "domodedovo_folder"
)

$failedUrlTypes = @()

foreach ($urlType in $urlTypes) {
    Write-Host ""
    Write-Host "=== MATRIX url_type=$urlType site=$Site ==="
    powershell -ExecutionPolicy Bypass -File scripts/run_form_matrix.ps1 `
        -Site $Site `
        -UrlType $urlType `
        -Pytest $Pytest `
        -Python $Python `
        -FailOnTestFailures $FailOnTestFailures

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failedUrlTypes += "$urlType(exit=$exitCode)"
    }
}

$allSummaryOut = "artifacts/reports/$Site/_all_url_types_form_matrix_summary.md"
Write-Host ""
Write-Host "Building all-url-types summary -> $allSummaryOut"
& $Python scripts/summarize_form_matrix.py `
    --site $Site `
    --output $allSummaryOut

$summaryExitCode = $LASTEXITCODE
if ($summaryExitCode -ne 0) {
    Write-Host "All-url-types summary build failed with exit code $summaryExitCode"
    exit $summaryExitCode
}

if ($failedUrlTypes.Count -gt 0 -and $FailOnTestFailures) {
    Write-Host ""
    Write-Host "Some url_type matrix runs failed:"
    $failedUrlTypes | ForEach-Object { Write-Host " - $_" }
    exit 1
}

exit 0
