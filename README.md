# testNewAddressPoisk — пакет спецификаций для Codex

Этот архив содержит полноценный план разработки автотестов первой итерации А/Б-теста поиска новой адрески на лендингах.

Главное правило реализации: **каждый кейс должен быть отдельным pytest test item**. Нельзя делать один тест, который циклом прогоняет все адреса, URL или формы.

## Рабочий репозиторий

Код автотестов планируется вести в репозитории:

```text
https://github.com/deidolinde-maker/AB_test_lending.git
```

Важно: этот пакет спецификаций не нужно автоматически коммитить в репозиторий. Репозиторий указан как место дальнейшей разработки и реализации проекта.

## Что внутри

```text
00_full_development_plan.md      Полная спека разработки
01_codex_prompt.md               Короткий промт для Codex
02_test_cases_matrix.md          Матрица тестов и принципы генерации кейсов
03_architecture.md               Архитектура проекта и Page Object
04_definition_of_done.md         Definition of Done
config/sites.yaml                Шаблон сайтов и региональных URL
config/forms.yaml                Справочник форм и селекторов из входных файлов
config/search_data.yaml          Тестовые адреса A/v1 и B/v2
config/synonyms.yaml             Справочник синонимов из входных файлов
docs/open_questions.md           Открытые вопросы и ограничения
docs/source_files/               Исходные приложенные файлы задачи
```

## Быстрый запуск будущего проекта

```bash
pytest --site=mts_internet_online --variant=A --dataset=main_search -n auto
pytest --site=mts_internet_online --variant=B --dataset=main_search -n auto
pytest --site=mts_internet_online --dataset=forbidden_region -n auto
pytest --site=mts_internet_online --dataset=synonyms -n auto
```

## Scope первой итерации

Входит:

- cookie `testNewAddressPoisk`;
- назначение A/B в чистом контексте;
- управляемый запуск A и B через cookie;
- поиск улиц и домов в A/v1;
- поиск улиц и домов в B/v2;
- проверка `address_id` для A;
- проверка `house_id` для B;
- проверка v2 endpoints для B;
- изоляция старой и новой адрески;
- смежный поиск Москва / Московская область / Балашиха;
- негативная проверка Петрозаводска;
- смена региона внутри формы без изменения URL;
- региональная навигация без региона → Москва → Балашиха → Домодедово;
- синонимы;
- Allure-артефакты.

Не входит:

- отправка заявок;
- проверка `orders`;
- CRM;
- ТС;
- тарифы;
- Telegram-алерты.

## Jenkins запуск

Для CI добавлены:

- `Jenkinsfile` — пайплайн установки зависимостей, прогона матрицы и архивации артефактов;
- `scripts/run_form_matrix.ps1` — матрица для одного `url_type` + отчет;
- `scripts/run_form_matrix_all.ps1` — матрица для всех `url_type` + общий отчет;
- `scripts/summarize_form_matrix.py` — сводка по статусам и сигнатурам падений;
- `scripts/run_dataset_suite.ps1` — прогон полного набора датасетов первой итерации;
- `scripts/summarize_dataset_suite.py` — сводка по датасетам.
- Linux-раннеры для Jenkins:
  - `scripts/run_form_matrix.sh`
  - `scripts/run_form_matrix_all.sh`
  - `scripts/run_dataset_suite.sh`

Пример локального запуска под Jenkins-режим:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_form_matrix_all.ps1 `
  -Site mts_internet_online `
  -Pytest pytest `
  -Python python `
  -FailOnTestFailures $false
```

Отчеты сохраняются в:

- `artifacts/allure-results/<site>/...`
- `artifacts/reports/<site>/<url_type>/form_matrix_summary.md`
- `artifacts/reports/<site>/_all_url_types_form_matrix_summary.md`
- `artifacts/reports/<site>/datasets/<run_tag>/dataset_suite_summary.md`

Параметр Jenkins `RUN_SUITE`:

- `form_matrix` — только A/B form matrix;
- `dataset_suite` — только датасеты `main_search/isolation/adjacent/forbidden_region/synonyms`;
- `both` — оба контура;
- `single_case` — запуск одного кейса по фильтрам.

Параметры для `RUN_SUITE=single_case`:

- `CASE_DATASET` — один датасет (`main_search/isolation/adjacent/forbidden_region/synonyms`);
- `CASE_URL_TYPE` — `domain_without_region|moscow_subdomain|balashikha_folder|domodedovo_folder`;
- `CASE_VARIANT` — `A` или `B`;
- `CASE_FORM` — `profit|connection|checkaddress|undecided|moving|express_connection`;
- `CASE_ID` — выпадающий список `case_id` из `config/search_data.yaml` (или `all`).

Кэш и очистка в Jenkins:

- кэш Python пакетов: `PIP_CACHE_DIR=${JENKINS_HOME}\\cache\\pip`;
- кэш Playwright браузеров: `PLAYWRIGHT_BROWSERS_PATH=${JENKINS_HOME}\\cache\\ms-playwright`;
- зависимости переустанавливаются только при изменении `requirements.txt` (по SHA256);
- ретеншн билдов/артефактов через `buildDiscarder` по дням и количеству;
- периодическая очистка старых `archive` и `allure-report` (параметры `ENABLE_PERIODIC_ARTIFACT_PURGE`, `PERIODIC_PURGE_EVERY`).
