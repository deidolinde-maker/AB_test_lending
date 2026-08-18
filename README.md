# lendings — автотесты форм/лендингов (Playwright + pytest)

Проект для UI‑проверок лендингов и отправки заявок, с Telegram‑уведомлениями и ежедневной сводкой.

## Быстрый старт

### 1) Установить зависимости

Рекомендуется виртуальное окружение.

```bash
python -m pip install -r requirements.txt
```

### 2) Запустить тесты

Пример (параллельно):

```bash
python -m pytest -n 2 -v
```

Запуск конкретного теста по ключу:

```bash
python -m pytest -n 2 -v -k test_choose_region_perelinkovka
```

Запуск одного теста много раз подряд:

- через плагин `pytest-repeat`:

```bash
python -m pip install pytest-repeat
python -m pytest -n 2 -v -k test_choose_region_perelinkovka --count=20
```

## Allure

Генерация результатов:

```bash
python -m pytest -n 2 -v --alluredir=allure-results
```

Если нужно не “падать” сборкой при фейлах (например, чтобы всё равно собрать отчёт):

```bash
python -m pytest -n 2 -v --alluredir=allure-results || true
```

## Jenkins

### Расписание (раз в 2 часа)

В **Build periodically**:

```text
H */2 * * *
```

или строго в 00 минут:

```text
0 */2 * * *
```

### Важные переменные окружения

#### Для параллельного запуска (`-n`)

- **`ALERTS_RUN_ID`** — строковый идентификатор прогона (нужен для дедупа при xdist).
  - Рекомендуемо в Jenkins: `ALERTS_RUN_ID=$BUILD_ID` (или `$BUILD_NUMBER`).

#### Куда писать состояние/счётчики алертов (межпрогонно)

- **`ALERTS_STATE_PATH`** — путь к `alerts_state.json` (fixed/active состояние).
- **`ERRORS_COUNT_PATH`** — путь к `errors_count.json` (накопительные повторы).

Пример для Jenkins (Linux):

```text
ALERTS_STATE_PATH=/var/lib/jenkins/alerts_state.json
ERRORS_COUNT_PATH=/var/lib/jenkins/errors_count.json
```

#### Дедуп‑файлы для параллели

- **`ALERTS_FLAG_DIR`** — базовая директория для run‑scoped флагов/логов.
  - По умолчанию: `.alerts_flags`

Внутри создаются:
- `.alerts_flags/<ALERTS_RUN_ID>/*.flag` — флаги дедупа;
- `.alerts_flags/<ALERTS_RUN_ID>/failed_tests/*.jsonl` — какие тесты реально падали (для fixed при xdist);
- `.alerts_flags/<ALERTS_RUN_ID>/executed_tests/*.jsonl` — какие тесты выполнялись (чтобы не “фиксить” не запущенные тесты).

#### Ручная фиксация cookie для AB-ветки

Если нужно принудительно зафиксировать вариант до первого `page.goto`, можно задать cookie через переменные окружения:

```text
COOKIE_OVERRIDES=testNewAddressPoisk=A;AB_wp_theme_variant=A
```

Поддерживаются и отдельные переменные:
- `TESTNEWADDRESSPOISK_COOKIE_VALUE`
- `AB_WP_THEME_VARIANT_COOKIE_VALUE`
- `THEME_AB_VARIANT_COOKIE_VALUE`

Значения `disabled`, `none`, `off`, `false`, `0` считаются пустыми и не проставляются.

## Telegram‑уведомления (алерты)

Логика реализована в `conftest.py`.

### Transport: direct vs proxy

- По умолчанию используется прямой транспорт (`BOT_TOKEN` + `CHAT_ID`).
- Для переключения на proxy задайте:
  - `USE_TELEGRAM_PROXY=true`
  - `TELEGRAM_PROXY_URL`
  - `TELEGRAM_PROXY_AUTH_SECRET`
  - `TELEGRAM_PROXY_CREDS`
- При `USE_TELEGRAM_PROXY=true` и отсутствии обязательных `TELEGRAM_PROXY_*`
  выводится fail-fast сообщение в логи, без печати секретов.

### Что считается “ошибкой” и “исправлением”

- **Падение теста** → отправляется уведомление в TG по расписанию повторов (см. ниже).
- **Исправление** → отправляется “✅ исправлена”, когда тест:
  - выполнялся в текущем прогоне, и
  - в текущем прогоне не упал,
  - при этом в прошлых прогонах был активен (`active=true`).

Ключ алертов/счётчиков — **уникальный `nodeid` теста**, чтобы одинаковые `@allure.title(...)` не склеивались.

### Накопительный эффект (повторы)

Накопительный счётчик ведётся в `errors_count.json` → `by_test[domain][nodeid]`.

Уведомления по “повторам” шлются по расписанию:
- 1‑й
- 4‑й
- 10‑й
- далее каждый 10‑й (20, 30, 40, ...)

После “✅ исправлена” счётчик по тесту **сбрасывается/удаляется**.

### URL в алерте

В сообщении показывается **URL, на котором упали** (приоритет):
1) URL из текста ошибки (если Playwright указал target)
2) наиболее “специфичный” URL из параметра теста / `page.url` (с путём/квери)
3) URL из маркеров (`allure.feature(...)`) как фолбэк

## Ежедневная/периодическая сводка (daily report)

Скрипт: `tools/daily_report.py`

- Источник данных: файл `.run_summaries.jsonl` (пишется в конце каждого прогона из `conftest.py`).
- Период отчёта: **текущие сутки по МСК** (по умолчанию с `00:00 MSK` до текущего момента).
- В отчёте добавляется строка `🗓 Период: ... (MSK)`.

Если нужно сместить начало дня (например, с `01:00 MSK`), задайте:

```text
MSK_DAY_START_HOUR=1
```

Запуск вручную:

```bash
python tools/daily_report.py
```

## Частые проблемы

### `__main__.py: error: unrecognized arguments: -n`

Опция `-n` требует плагин `pytest-xdist`.

```bash
python -m pip install pytest-xdist
```

### `@pytest.mark.skip(...)` всё равно “падает”

Пропущенные тесты не должны попадать в алерты/таблицу как failed — эта защита встроена в `conftest.py`.

# lendings
