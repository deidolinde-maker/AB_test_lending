#!/usr/bin/env bash
set -euo pipefail

site="mts_internet_online"
pytest_bin="pytest"
python_bin="python"
fail_on_test_failures="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) site="$2"; shift 2 ;;
    --pytest) pytest_bin="$2"; shift 2 ;;
    --python) python_bin="$2"; shift 2 ;;
    --fail-on-test-failures) fail_on_test_failures="$2"; shift 2 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

url_types=(
  "domain_without_region"
  "moscow_subdomain"
  "balashikha_folder"
  "domodedovo_folder"
)

failed_url_types=()

for url_type in "${url_types[@]}"; do
  echo
  echo "=== MATRIX url_type=${url_type} site=${site} ==="
  set +e
  bash scripts/run_form_matrix.sh \
    --site "${site}" \
    --url-type "${url_type}" \
    --pytest "${pytest_bin}" \
    --python "${python_bin}" \
    --fail-on-test-failures "${fail_on_test_failures}"
  exit_code=$?
  set -e
  if [[ ${exit_code} -ne 0 ]]; then
    failed_url_types+=("${url_type}(exit=${exit_code})")
  fi
done

all_summary_out="artifacts/reports/${site}/_all_url_types_form_matrix_summary.md"
echo
echo "Building all-url-types summary -> ${all_summary_out}"
"${python_bin}" scripts/summarize_form_matrix.py \
  --site "${site}" \
  --output "${all_summary_out}"

if [[ ${#failed_url_types[@]} -gt 0 && "${fail_on_test_failures}" == "true" ]]; then
  echo
  echo "Some url_type matrix runs failed:"
  for row in "${failed_url_types[@]}"; do
    echo " - ${row}"
  done
  exit 1
fi

exit 0
