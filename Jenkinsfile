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
    string(name: 'PYTEST_BIN', defaultValue: 'pytest', description: 'Pytest command (for example .venv/bin/pytest)')
    string(name: 'PYTHON_BIN', defaultValue: 'python3', description: 'Python command (for example .venv/bin/python)')
    choice(name: 'RUN_SUITE', choices: ['form_matrix', 'dataset_suite', 'both'], description: 'Which suite to run')
    booleanParam(name: 'FAIL_ON_TEST_FAILURES', defaultValue: false, description: 'If true, build fails when any test run has failed tests')
    booleanParam(name: 'ENABLE_PERIODIC_ARTIFACT_PURGE', defaultValue: true, description: 'Every N builds, delete archived artifacts/allure reports of previous builds for this job.')
    string(name: 'PERIODIC_PURGE_EVERY', defaultValue: '5', description: 'Run full artifact purge every N-th build (integer >= 2).')
  }

  environment {
    PLAYWRIGHT_BROWSERS_PATH = '/var/lib/jenkins/cache/ms-playwright'
    PIP_CACHE_DIR = '/var/lib/jenkins/cache/pip'
    PIP_DISABLE_PIP_VERSION_CHECK = '1'
    PYTHONUNBUFFERED = '1'
    PYTHON_BIN_VENV = '.venv/bin/python'
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
        sh '''
          set -e
          echo "=== Cache diagnostics ==="
          echo "Workspace: $(pwd)"
          echo "PIP_CACHE_DIR=${PIP_CACHE_DIR}"
          echo "PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH}"

          if [ -x ".venv/bin/python" ]; then
            echo "[VENV] Reused: .venv exists"
            .venv/bin/python --version || true
          else
            echo "[VENV] Missing: .venv will be created"
          fi

          if [ -f "${REQ_HASH_FILE}" ]; then
            echo "[REQ_HASH] Found: $(cat "${REQ_HASH_FILE}")"
          else
            echo "[REQ_HASH] Missing: deps install expected"
          fi

          if [ -d "${PIP_CACHE_DIR}" ]; then
            echo "[PIP_CACHE] Found"
          else
            echo "[PIP_CACHE] Missing"
          fi

          if [ -d "${PLAYWRIGHT_BROWSERS_PATH}" ]; then
            echo "[PW_CACHE] Found"
            ls -1 "${PLAYWRIGHT_BROWSERS_PATH}" | head -n 10 || true
          else
            echo "[PW_CACHE] Missing"
          fi
          echo "========================="
        '''
      }
    }

    stage('Prepare Python') {
      steps {
        sh '''
          set -e
          mkdir -p "${PIP_CACHE_DIR}"

          base_py="${PYTHON_BIN}"
          if ! command -v "${base_py}" >/dev/null 2>&1; then
            if command -v python3 >/dev/null 2>&1; then
              base_py="python3"
              echo "Configured PYTHON_BIN='${PYTHON_BIN}' is unavailable. Fallback to '${base_py}'."
            elif command -v python >/dev/null 2>&1; then
              base_py="python"
              echo "Configured PYTHON_BIN='${PYTHON_BIN}' is unavailable. Fallback to '${base_py}'."
            else
              echo "No Python interpreter found. Install python3 (and python3-venv) on Jenkins agent."
              exit 127
            fi
          fi

          pybin="${PYTHON_BIN_VENV}"
          if [ ! -x "${pybin}" ]; then
            "${base_py}" -m venv .venv || true
          fi
          if [ ! -x "${pybin}" ]; then
            pybin="${base_py}"
          fi
          if [ -z "${pybin}" ]; then
            echo "Python binary is not resolved."
            exit 2
          fi

          echo "${pybin}" > "${PYTHON_BIN_FILE}"
          "${pybin}" --version

          current_hash="$(sha256sum requirements.txt | awk '{print $1}')"
          saved_hash=""
          if [ -f "${REQ_HASH_FILE}" ]; then
            saved_hash="$(cat "${REQ_HASH_FILE}")"
          fi

          need_install=0
          if [ ! -f "${REQ_HASH_FILE}" ]; then
            need_install=1
          fi
          if [ "${current_hash}" != "${saved_hash}" ]; then
            need_install=1
          fi
          if ! "${pybin}" -m pytest --version >/dev/null 2>&1; then
            need_install=1
          fi

          if [ "${need_install}" = "1" ]; then
            echo "Installing Python dependencies (first run or requirements changed)..."
            "${pybin}" -m pip install --cache-dir "${PIP_CACHE_DIR}" --upgrade pip
            "${pybin}" -m pip install --cache-dir "${PIP_CACHE_DIR}" -r requirements.txt
            echo "${current_hash}" > "${REQ_HASH_FILE}"
          else
            echo "Python dependencies already installed, skip pip install."
          fi
        '''
      }
    }

    stage('Install missing Playwright browsers') {
      steps {
        sh '''
          set -e
          mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}"
          pybin="$(cat "${PYTHON_BIN_FILE}")"
          if [ -z "${pybin}" ]; then
            echo "PYTHON_BIN_FILE is empty"
            exit 2
          fi

          if ls "${PLAYWRIGHT_BROWSERS_PATH}"/chromium-* >/dev/null 2>&1; then
            echo "Chromium already exists in shared Playwright cache."
          else
            echo "Installing Chromium into shared Playwright cache..."
            "${pybin}" -m playwright install chromium
          fi
        '''
      }
    }

    stage('Run Form Matrix (All url_type)') {
      when {
        expression { env.RUN_SUITE == 'form_matrix' || env.RUN_SUITE == 'both' }
      }
      steps {
        sh '''
          set -e
          pybin="$(cat "${PYTHON_BIN_FILE}")"
          chmod +x scripts/*.sh
          bash scripts/run_form_matrix_all.sh \
            --site "${SITE}" \
            --pytest "${PYTEST_BIN}" \
            --python "${pybin}" \
            --fail-on-test-failures "${FAIL_ON_TEST_FAILURES}"
        '''
      }
    }

    stage('Run Dataset Suite') {
      when {
        expression { env.RUN_SUITE == 'dataset_suite' || env.RUN_SUITE == 'both' }
      }
      steps {
        sh '''
          set -e
          pybin="$(cat "${PYTHON_BIN_FILE}")"
          chmod +x scripts/*.sh
          bash scripts/run_dataset_suite.sh \
            --site "${SITE}" \
            --pytest "${PYTEST_BIN}" \
            --python "${pybin}" \
            --fail-on-test-failures "${FAIL_ON_TEST_FAILURES}"
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
          sh '''
            set +e
            purge_every="${PERIODIC_PURGE_EVERY:-5}"
            if ! [ "${purge_every}" -ge 2 ] 2>/dev/null; then
              purge_every=5
            fi
            if ! [ "${BUILD_NUMBER}" -ge 1 ] 2>/dev/null; then
              echo "[PURGE] BUILD_NUMBER is not numeric, skip."
              exit 0
            fi
            mod=$(( BUILD_NUMBER % purge_every ))
            if [ "${mod}" -ne 0 ]; then
              echo "[PURGE] Skip: build #${BUILD_NUMBER} is not each ${purge_every}-th run."
              exit 0
            fi
            if [ -z "${JENKINS_HOME}" ] || [ -z "${JOB_NAME}" ]; then
              echo "[PURGE] JENKINS_HOME or JOB_NAME is empty, skip."
              exit 0
            fi

            job_path="$(printf '%s' "${JOB_NAME}" | sed 's#/#/jobs/#g')"
            builds_dir="${JENKINS_HOME}/jobs/${job_path}/builds"
            if [ ! -d "${builds_dir}" ]; then
              echo "[PURGE] Builds dir not found: ${builds_dir}"
              exit 0
            fi

            echo "[PURGE] Running periodic purge for ${JOB_NAME} at build #${BUILD_NUMBER} (every ${purge_every})"
            find "${builds_dir}" -mindepth 2 -maxdepth 2 -type d \\( -name archive -o -name allure-report \\) ! -path "${builds_dir}/${BUILD_NUMBER}/*" -print -exec rm -rf {} +
            echo "[PURGE] Done."
            exit 0
          '''
        } else {
          echo 'Periodic artifact purge disabled by parameter.'
        }
      }

      sh '''
        set +e
        rm -rf artifacts/videos .pytest_cache pytest-cache-files-* __pycache__ || true
        find . -type d -name "__pycache__" -prune -exec rm -rf {} +
        exit 0
      '''
    }
  }
}
