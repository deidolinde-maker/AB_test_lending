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
    choice(name: 'RUN_SUITE', choices: ['submit_matrix', 'form_matrix', 'dataset_suite', 'both', 'single_case'], description: 'Which suite to run. submit_matrix and form_matrix both run submit scenarios across all url types.')
    booleanParam(name: 'FAIL_ON_TEST_FAILURES', defaultValue: false, description: 'If true, build fails when any test run has failed tests')
    string(name: 'CASE_URL_TYPE', defaultValue: 'domain_without_region', description: 'Used when RUN_SUITE=single_case')
    choice(name: 'CASE_VARIANT', choices: ['all', 'A', 'B'], description: "Used when RUN_SUITE=single_case. 'all' runs both A and B.")
    choice(name: 'CASE_FORM', choices: ['all', 'profit', 'connection', 'checkaddress', 'undecided', 'moving', 'express_connection'], description: "Used when RUN_SUITE=single_case. 'all' runs all forms applicable for selected URL.")
    choice(
      name: 'CASE_DATASET',
      choices: ['main_search', 'isolation', 'adjacent', 'forbidden_region', 'synonyms', 'region_change', 'regional_navigation', 'ab_cookie'],
      description: 'Used when RUN_SUITE=single_case'
    )
    choice(
      name: 'CASE_ID',
      choices: [
        'all',
        'A_moscow_alabyan',
        'A_mo_domodedovo_lomonosova',
        'A_balashikha_ordzhonikidze',
        'B_moscow_lipovy_park',
        'B_mo_domodedovo_kolomiytsa',
        'B_balashikha_chekhova',
        'forbidden_A_petrozavodsk_lisitsynoy',
        'forbidden_B_petrozavodsk_tapiola'
      ],
      description: "Select case_id from config/search_data.yaml, or 'all' for all cases matching filters."
    )
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

    stage('Clean run artifacts') {
      steps {
        sh '''
          set +e
          rm -rf artifacts/allure-results artifacts/allure-results-merged artifacts/reports || true
          mkdir -p artifacts/allure-results artifacts/reports
          echo "Workspace artifacts cleaned before test run."
          exit 0
        '''
      }
    }

    stage('Run Form Matrix (All url_type)') {
      when {
        expression { env.RUN_SUITE == 'submit_matrix' || env.RUN_SUITE == 'form_matrix' || env.RUN_SUITE == 'both' }
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

    stage('Run Single Case') {
      when {
        expression { env.RUN_SUITE == 'single_case' }
      }
      steps {
        sh '''
          set -e
          pybin="$(cat "${PYTHON_BIN_FILE}")"
          chmod +x scripts/*.sh
          bash scripts/run_dataset_suite.sh \
            --site "${SITE}" \
            --dataset-filter "${CASE_DATASET}" \
            --url-type "${CASE_URL_TYPE}" \
            --variant "${CASE_VARIANT}" \
            --form "${CASE_FORM}" \
            --case-id "${CASE_ID}" \
            --pytest "${PYTEST_BIN}" \
            --python "${pybin}" \
            --fail-on-test-failures "${FAIL_ON_TEST_FAILURES}"
        '''
      }
    }
  }

  post {
    always {
      sh '''
        set +e
        merged_dir="artifacts/allure-results-merged"
        rm -rf "${merged_dir}" || true
        mkdir -p "${merged_dir}"

        if [ -d "artifacts/allure-results" ]; then
          find artifacts/allure-results -type f -exec cp -f {} "${merged_dir}/" \\;
          files_count="$(find "${merged_dir}" -type f | wc -l | tr -d ' ')"
          echo "[ALLURE_MERGE] merged files: ${files_count}"
        else
          echo "[ALLURE_MERGE] source dir artifacts/allure-results not found"
        fi
        exit 0
      '''

      archiveArtifacts artifacts: 'artifacts/**, .requirements.sha256, .python_bin', allowEmptyArchive: true

      script {
        try {
          allure includeProperties: false, jdk: '', results: [[path: 'artifacts/allure-results-merged']]
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
