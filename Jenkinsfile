pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(
      daysToKeepStr: '21',
      numToKeepStr: '40',
      artifactDaysToKeepStr: '10',
      artifactNumToKeepStr: '12'
    ))
  }

  parameters {
    string(name: 'SITE', defaultValue: 'mts_internet_online', description: 'Site key from config/sites.yaml')
    string(name: 'PYTEST_BIN', defaultValue: 'pytest', description: 'Pytest command (for example .venv\\Scripts\\pytest.exe)')
    string(name: 'PYTHON_BIN', defaultValue: 'python', description: 'Python command (for example .venv\\Scripts\\python.exe)')
    choice(name: 'RUN_SUITE', choices: ['form_matrix', 'dataset_suite', 'both'], description: 'Which suite to run')
    booleanParam(name: 'FAIL_ON_TEST_FAILURES', defaultValue: false, description: 'If true, build fails when any test run has failed tests')
    booleanParam(name: 'ENABLE_PERIODIC_ARTIFACT_PURGE', defaultValue: true, description: 'Every N builds, delete archived artifacts/allure reports of previous builds for this job.')
    string(name: 'PERIODIC_PURGE_EVERY', defaultValue: '5', description: 'Run full artifact purge every N-th build (integer >= 2).')
  }

  environment {
    PIP_CACHE_DIR = "${JENKINS_HOME}\\cache\\pip"
    PLAYWRIGHT_BROWSERS_PATH = "${JENKINS_HOME}\\cache\\ms-playwright"
    PIP_DISABLE_PIP_VERSION_CHECK = '1'
    PYTHONUNBUFFERED = '1'
    PYTHON_BIN_VENV = '.venv\\Scripts\\python.exe'
    PYTHON_BIN_FILE = '.python_bin'
    REQ_HASH_FILE = '.requirements.sha256'
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Validate parameters') {
      steps {
        script {
          if ((params.PERIODIC_PURGE_EVERY ?: '').trim() && !((params.PERIODIC_PURGE_EVERY as String) ==~ /\d+/)) {
            error('PERIODIC_PURGE_EVERY must be an integer >= 2.')
          }
        }
      }
    }

    stage('Cache diagnostics') {
      steps {
        powershell '''
          $ErrorActionPreference = "Stop"
          Write-Host "=== Cache diagnostics ==="
          Write-Host "Workspace: $PWD"
          Write-Host "PIP_CACHE_DIR=$env:PIP_CACHE_DIR"
          Write-Host "PLAYWRIGHT_BROWSERS_PATH=$env:PLAYWRIGHT_BROWSERS_PATH"

          if (Test-Path -LiteralPath ".venv\\Scripts\\python.exe") {
            Write-Host "[VENV] Reused: .venv exists"
            & ".venv\\Scripts\\python.exe" --version
          } else {
            Write-Host "[VENV] Missing: .venv will be created"
          }

          if (Test-Path -LiteralPath $env:REQ_HASH_FILE) {
            $hash = (Get-Content -LiteralPath $env:REQ_HASH_FILE -Raw).Trim()
            Write-Host "[REQ_HASH] Found: $hash"
          } else {
            Write-Host "[REQ_HASH] Missing: deps install expected"
          }

          if (Test-Path -LiteralPath $env:PIP_CACHE_DIR) {
            Write-Host "[PIP_CACHE] Found"
          } else {
            Write-Host "[PIP_CACHE] Missing"
          }

          if (Test-Path -LiteralPath $env:PLAYWRIGHT_BROWSERS_PATH) {
            Write-Host "[PW_CACHE] Found"
            Get-ChildItem -LiteralPath $env:PLAYWRIGHT_BROWSERS_PATH -Name -ErrorAction SilentlyContinue | Select-Object -First 10
          } else {
            Write-Host "[PW_CACHE] Missing"
          }
          Write-Host "========================="
        '''
      }
    }

    stage('Prepare Python') {
      steps {
        powershell '''
          $ErrorActionPreference = "Stop"

          New-Item -ItemType Directory -Path $env:PIP_CACHE_DIR -Force | Out-Null

          $pybin = $env:PYTHON_BIN_VENV
          if (-not (Test-Path -LiteralPath $pybin)) {
            & $env:PYTHON_BIN -m venv .venv
          }
          if (-not (Test-Path -LiteralPath $pybin)) {
            $pybin = $env:PYTHON_BIN
          }
          if (-not $pybin) {
            throw "Python binary is not resolved."
          }

          Set-Content -LiteralPath $env:PYTHON_BIN_FILE -Value $pybin -Encoding UTF8
          & $pybin --version

          $currentHash = (Get-FileHash -LiteralPath "requirements.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
          $savedHash = ""
          if (Test-Path -LiteralPath $env:REQ_HASH_FILE) {
            $savedHash = (Get-Content -LiteralPath $env:REQ_HASH_FILE -Raw).Trim().ToLowerInvariant()
          }

          $needInstall = $false
          if (-not (Test-Path -LiteralPath $env:REQ_HASH_FILE)) { $needInstall = $true }
          if ($currentHash -ne $savedHash) { $needInstall = $true }

          & $pybin -m pytest --version *> $null
          if ($LASTEXITCODE -ne 0) { $needInstall = $true }

          if ($needInstall) {
            Write-Host "Installing Python dependencies (first run or requirements changed)..."
            & $pybin -m pip install --cache-dir "$env:PIP_CACHE_DIR" --upgrade pip
            if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip" }
            & $pybin -m pip install --cache-dir "$env:PIP_CACHE_DIR" -r requirements.txt
            if ($LASTEXITCODE -ne 0) { throw "Failed to install requirements" }
            Set-Content -LiteralPath $env:REQ_HASH_FILE -Value $currentHash -Encoding UTF8
          } else {
            Write-Host "Python dependencies already installed, skip pip install."
          }
        '''
      }
    }

    stage('Install missing Playwright browsers') {
      steps {
        powershell '''
          $ErrorActionPreference = "Stop"
          New-Item -ItemType Directory -Path $env:PLAYWRIGHT_BROWSERS_PATH -Force | Out-Null

          $pybin = (Get-Content -LiteralPath $env:PYTHON_BIN_FILE -Raw).Trim()
          if (-not $pybin) { throw "PYTHON_BIN_FILE is empty" }

          $chromiumExists = Get-ChildItem -LiteralPath $env:PLAYWRIGHT_BROWSERS_PATH -Filter "chromium-*" -ErrorAction SilentlyContinue
          if ($chromiumExists) {
            Write-Host "Chromium already exists in shared Playwright cache."
          } else {
            Write-Host "Installing Chromium into shared Playwright cache..."
            & $pybin -m playwright install chromium
            if ($LASTEXITCODE -ne 0) { throw "Failed to install Chromium browser" }
          }
        '''
      }
    }

    stage('Run Form Matrix (All url_type)') {
      when {
        expression { env.RUN_SUITE == 'form_matrix' || env.RUN_SUITE == 'both' }
      }
      steps {
        powershell '''
          $ErrorActionPreference = "Stop"
          $pybin = (Get-Content -LiteralPath $env:PYTHON_BIN_FILE -Raw).Trim()
          powershell -ExecutionPolicy Bypass -File scripts/run_form_matrix_all.ps1 `
            -Site "${env:SITE}" `
            -Pytest "${env:PYTEST_BIN}" `
            -Python "$pybin" `
            -FailOnTestFailures ([System.Convert]::ToBoolean("${env:FAIL_ON_TEST_FAILURES}"))
        '''
      }
    }

    stage('Run Dataset Suite') {
      when {
        expression { env.RUN_SUITE == 'dataset_suite' || env.RUN_SUITE == 'both' }
      }
      steps {
        powershell '''
          $ErrorActionPreference = "Stop"
          $pybin = (Get-Content -LiteralPath $env:PYTHON_BIN_FILE -Raw).Trim()
          powershell -ExecutionPolicy Bypass -File scripts/run_dataset_suite.ps1 `
            -Site "${env:SITE}" `
            -Pytest "${env:PYTEST_BIN}" `
            -Python "$pybin" `
            -FailOnTestFailures ([System.Convert]::ToBoolean("${env:FAIL_ON_TEST_FAILURES}"))
        '''
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'artifacts/**, .requirements.sha256, .python_bin', allowEmptyArchive: true

      script {
        try {
          allure includeProperties: false, jdk: '', results: [[path: 'artifacts/allure-results']]
          echo 'Allure report published in Jenkins UI.'
        } catch (Exception e) {
          echo "Allure publish skipped: ${e.getMessage()}"
        }
      }

      script {
        if (params.ENABLE_PERIODIC_ARTIFACT_PURGE) {
          powershell '''
            $ErrorActionPreference = "Continue"

            $purgeEvery = 5
            try {
              $parsed = [int]$env:PERIODIC_PURGE_EVERY
              if ($parsed -ge 2) { $purgeEvery = $parsed }
            } catch {}

            try {
              $buildNumber = [int]$env:BUILD_NUMBER
            } catch {
              Write-Host "[PURGE] BUILD_NUMBER is not numeric, skip."
              exit 0
            }

            if (($buildNumber % $purgeEvery) -ne 0) {
              Write-Host "[PURGE] Skip: build #$buildNumber is not each $purgeEvery-th run."
              exit 0
            }

            if (-not $env:JENKINS_HOME -or -not $env:JOB_NAME) {
              Write-Host "[PURGE] JENKINS_HOME or JOB_NAME is empty, skip."
              exit 0
            }

            $jobParts = $env:JOB_NAME -split '/'
            $jobsRoot = Join-Path $env:JENKINS_HOME 'jobs'
            $jobPath = $jobsRoot
            foreach ($part in $jobParts) {
              $jobPath = Join-Path $jobPath $part
              $jobPath = Join-Path $jobPath 'jobs'
            }
            $jobPath = Split-Path -Path $jobPath -Parent
            $buildsDir = Join-Path $jobPath 'builds'

            if (-not (Test-Path -LiteralPath $buildsDir)) {
              Write-Host "[PURGE] Builds dir not found: $buildsDir"
              exit 0
            }

            Write-Host "[PURGE] Running periodic purge for $env:JOB_NAME at build #$buildNumber (every $purgeEvery)"
            $buildDirs = Get-ChildItem -LiteralPath $buildsDir -Directory -ErrorAction SilentlyContinue
            foreach ($buildDir in $buildDirs) {
              if ($buildDir.Name -eq "$buildNumber") { continue }
              $archiveDir = Join-Path $buildDir.FullName 'archive'
              $allureDir = Join-Path $buildDir.FullName 'allure-report'
              if (Test-Path -LiteralPath $archiveDir) {
                Remove-Item -LiteralPath $archiveDir -Recurse -Force -ErrorAction SilentlyContinue
              }
              if (Test-Path -LiteralPath $allureDir) {
                Remove-Item -LiteralPath $allureDir -Recurse -Force -ErrorAction SilentlyContinue
              }
            }
            Write-Host "[PURGE] Done."
            exit 0
          '''
        } else {
          echo 'Periodic artifact purge disabled by parameter.'
        }
      }

      powershell '''
        $ErrorActionPreference = "Continue"
        Remove-Item -LiteralPath "artifacts\\videos" -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ".pytest_cache" -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath . -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
          Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
      '''
    }
  }
}
