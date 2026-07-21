# AB_test_lending_e2e

Автотесты первой итерации A/B-поиска адреса для лендингов (`v1` vs `v2`) с запуском в Jenkins и отчетами в Allure.

## Что проверяет проект

- корректную установку и сохранение A/B cookie (`testNewAddressPoisk`);
- сценарии поиска адреса по улицам/домам для вариантов `A` и `B`;
- соответствие ожидаемого ID (`address_id` для `A`, `house_id` для `B`);
- изоляцию старой/новой адрески;
- смежные и запрещенные регионы;
- смену региона внутри формы без смены URL;
- региональную навигацию;
- словарь синонимов;
- отдельные технические проверки (`ab_cookie`).

Дополнительно поддерживается второй site scope для stage-площадок:

- `stage_project`:
  - `https://stage-project.ru/`;
  - `https://moskva.stage-project.ru/`;
  - `https://balashiha.stage-project.ru/`;
  - `https://domodedovo.stage-project.ru/`.

## Технологии

- `pytest`
- `pytest-playwright`
- `playwright`
- `allure-pytest`

## Структура

```text
AB_test_lending_repo/
  config/
    sites.yaml
    forms.yaml
    search_data.yaml
    synonyms.yaml
  tests/
    test_search_variant_a.py
    test_search_variant_b.py
    test_search_isolation.py
    test_adjacent_search.py
    test_forbidden_region.py
    test_synonyms.py
    test_region_change_inside_form.py
    test_regional_navigation.py
    test_ab_cookie.py
  scripts/
    run_form_matrix.sh
    run_form_matrix_all.sh
    run_dataset_suite.sh
    summarize_form_matrix.py
    summarize_dataset_suite.py
  Jenkinsfile
  conftest.py
```

## Датасеты

Поддерживаемые датасеты:

- `main_search`
- `isolation`
- `adjacent`
- `forbidden_region`
- `synonyms`
- `region_change`
- `regional_navigation`
- `ab_cookie`

Источник тестовых адресов и ожиданий: `config/search_data.yaml`.

## Локальный запуск

### 1) Установка

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 2) Базовые команды

Важно: e2e-сценарии запускаются с `--run-e2e`.

```bash
# A / main search
pytest -q -s tests/test_search_variant_a.py::test_search_variant_a \
  --run-e2e --site mts_internet_online --dataset main_search --variant A

# B / main search
pytest -q -s tests/test_search_variant_b.py::test_search_variant_b \
  --run-e2e --site mts_internet_online --dataset main_search --variant B

# Любой датасет через общий раннер
bash scripts/run_dataset_suite.sh \
  --site mts_internet_online \
  --dataset-filter regional_navigation \
  --url-type domain_without_region \
  --variant all \
  --form all \
  --case-id all \
  --python .venv/bin/python \
  --pytest pytest \
  --fail-on-test-failures false
```

### 3) Полезные фильтры

- `--dataset`: выбор датасета;
- `--variant`: `all|A|B`;
- `--url-type`: `all|domain_without_region|moscow_subdomain|balashikha_folder|domodedovo_folder`;
- `--form`: `all|profit|connection|checkaddress|undecided|moving|express_connection`;
- `--case-id`: конкретный кейс или `all`;
- `--video-mode`: `off|on_failure|always` (по умолчанию `on_failure`).

## Jenkins

Pipeline описан в `Jenkinsfile` и рассчитан на Linux-агент.

### Параметры job

- `SITE` — сайт из `config/sites.yaml`.
- `PYTEST_BIN` — команда pytest (по умолчанию `pytest`).
- `PYTHON_BIN` — python (по умолчанию `python3`).
- `RUN_SUITE` — `form_matrix | dataset_suite | both | single_case`.
- `FAIL_ON_TEST_FAILURES` — фейлить build при падениях тестов.
- `CASE_URL_TYPE` — для `RUN_SUITE=single_case`.
- `CASE_VARIANT` — `all | A | B`.
- `CASE_FORM` — `all | profit | connection | checkaddress | undecided | moving | express_connection`.
- `CASE_DATASET` — один из датасетов.
- `CASE_ID` — `all` или конкретный `case_id` из `search_data`.
- `ENABLE_PERIODIC_ARTIFACT_PURGE` — включить периодическую очистку архивов.
- `PERIODIC_PURGE_EVERY` — каждые N билдов (N >= 2).

### Режимы запуска

- `form_matrix` — прогон A/B по матрице форм и url_type.
- `dataset_suite` — прогон всех датасетов.
- `both` — оба режима подряд.
- `single_case` — таргетированный запуск по фильтрам.

### Кэш и подготовка окружения

- Python зависимости кэшируются в `/var/lib/jenkins/cache/pip`.
- Playwright браузеры кэшируются в `/var/lib/jenkins/cache/ms-playwright`.
- Переустановка зависимостей только при изменении `requirements.txt` (SHA-файл `.requirements.sha256`).

## Отчеты и артефакты

### Allure

- Allure-results собираются в `artifacts/allure-results/...`.
- В `post` шаге пайплайна результаты мерджатся в `artifacts/allure-results-merged`.
- Отчет публикуется в Jenkins через плагин Allure.

### Сводки

- Матрица форм:
  - `artifacts/reports/<site>/<url_type>/form_matrix_summary.md`
  - `artifacts/reports/<site>/_all_url_types_form_matrix_summary.md`
- Датасеты:
  - `artifacts/reports/<site>/datasets/<run_tag>/dataset_suite_summary.md`

### Мини-баг-репорт по кейсу

Для упавших тестов автоматически формируется:

- текстовый attachment `mini_bug_report_ru_text` в Allure;
- markdown-файл `mini_bug_report_ru` (attachment);
- файл на диске: `artifacts/reports/cases/<pytest_nodeid>.md`.

Шаблон отчета:

- Кейс
- Шаги
- Ожидаемый результат
- Фактический результат
- Описание бага

## Очистка и контроль объема

- Перед прогоном очищаются:
  - `artifacts/allure-results`
  - `artifacts/allure-results-merged`
  - `artifacts/reports`
- После прогона очищаются:
  - `artifacts/videos`
  - `.pytest_cache`
  - `__pycache__`
- Периодическая очистка Jenkins-архивов работает по параметрам purge.

## Важные нюансы

- Для `B` часть кейсов может падать из-за реального продуктового поведения (например, v1 endpoint вместо v2 или неожиданный регион в саджесте) — это фиксируется как валидный баг-сигнал.
- `single_case` с `CASE_VARIANT=all` запускает оба варианта.
- `CASE_FORM=all` запускает все формы, применимые для выбранного URL.

## Быстрый smoke после изменений

```bash
bash scripts/run_dataset_suite.sh \
  --site mts_internet_online \
  --dataset-filter ab_cookie \
  --url-type domain_without_region \
  --variant all \
  --form all \
  --case-id all \
  --python .venv/bin/python \
  --pytest pytest \
  --fail-on-test-failures false
```
