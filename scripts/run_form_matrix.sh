#!/usr/bin/env bash
set -euo pipefail

site="mts_internet_online"
url_type="moscow_subdomain"
pytest_bin="pytest"
python_bin="python"
fail_on_test_failures="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) site="$2"; shift 2 ;;
    --url-type) url_type="$2"; shift 2 ;;
    --pytest) pytest_bin="$2"; shift 2 ;;
    --python) python_bin="$2"; shift 2 ;;
    --fail-on-test-failures) fail_on_test_failures="$2"; shift 2 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

forms=(
  "profit"
  "connection"
  "checkaddress"
  "undecided"
  "moving"
  "express_connection"
)
variants=("A" "B")

failed_runs=()

for variant in "${variants[@]}"; do
  for form in "${forms[@]}"; do
    allure_dir="artifacts/allure-results/${site}/${url_type}/${variant}/${form}"
    mkdir -p "${allure_dir}"

    echo
    echo "=== RUN variant=${variant} form=${form} site=${site} url_type=${url_type} ==="

    set +e
    "${pytest_bin}" \
      -q -s \
      tests/test_search_variant_a.py::test_search_variant_a \
      tests/test_search_variant_b.py::test_search_variant_b \
      --run-e2e \
      --site "${site}" \
      --url-type "${url_type}" \
      --form "${form}" \
      --variant "${variant}" \
      --alluredir "${allure_dir}"
    exit_code=$?
    set -e

    if [[ ${exit_code} -ne 0 ]]; then
      failed_runs+=("variant=${variant} form=${form} site=${site} url_type=${url_type} exit_code=${exit_code}")
      echo "RUN FAILED: variant=${variant} form=${form} exit_code=${exit_code}"
    fi
  done
done

echo
echo "Form-matrix run completed."

summary_out="artifacts/reports/${site}/${url_type}/form_matrix_summary.md"
echo "Building summary report -> ${summary_out}"
"${python_bin}" scripts/summarize_form_matrix.py \
  --site "${site}" \
  --url-type "${url_type}" \
  --output "${summary_out}"

if [[ ${#failed_runs[@]} -gt 0 ]]; then
  echo
  echo "Failed runs:"
  for row in "${failed_runs[@]}"; do
    echo " - ${row}"
  done
  if [[ "${fail_on_test_failures}" == "true" ]]; then
    exit 1
  fi
fi

exit 0
