import os
import pytest
import allure
import time
import json
import threading
import re
import html
import requests
from datetime import datetime
import hashlib
from urllib.parse import urlparse
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import gspread
from slugify import slugify
from playwright.sync_api import sync_playwright, Error as PlaywrightError
# Загружаем переменные окружения из .env файла
load_dotenv()

try:
    from config import bot, chat_id
except Exception:
    bot = None
    chat_id = None

# Хранилище метаданных по тестам для итогового отчета (title, description, feature/url)
TEST_META = {}


def pytest_addoption(parser):
    parser.addoption("--site", action="store", default="all")
    parser.addoption("--url-type", action="store", default="all")
    parser.addoption("--variant", action="store", default="all", choices=["all", "A", "B"])
    parser.addoption(
        "--dataset",
        action="store",
        default="submit_applications",
        choices=[
            "all",
            "submit_applications",
            "form_open_smoke",
            "json_store_smoke",
            "submit_success_marker_smoke",
            "mini_bug_report_smoke",
            "ab_cookie",
            "forbidden_region",
            "isolation",
            "adjacent",
            "region_change",
            "synonyms",
            "regional_navigation",
        ],
    )
    parser.addoption("--form", action="store", default="all")
    parser.addoption("--case-id", action="store", default="all")
    parser.addoption("--run-e2e", action="store_true", default=False)
    parser.addoption("--applications-json-path", action="store", default=None)
    parser.addoption("--run-id", action="store", default=None)
    parser.addoption("--build-number", action="store", default=None)
    parser.addoption(
        "--fail-on-missing-ym-uid",
        action="store",
        default=None,
        choices=["true", "false"],
    )
    parser.addoption(
        "--video-mode",
        action="store",
        default="on_failure",
        choices=["off", "on_failure", "always"],
    )

# ==== Allure step tracking (capture last step name per test thread) ====
_ORIGINAL_ALLURE_STEP = allure.step
_TLS = threading.local()

class _StepProxy:
    def __init__(self, cm, name):
        self._cm = cm
        self._name = name

    def __enter__(self):
        try:
            _TLS.last_step_name = self._name
        except Exception:
            pass
        return self._cm.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._cm.__exit__(exc_type, exc_val, exc_tb)


def _patched_allure_step(name: str):
    return _StepProxy(_ORIGINAL_ALLURE_STEP(name), name)


try:
    allure.step = _patched_allure_step  # type: ignore
except Exception:
    pass


# ==== Alerts configuration and state ====
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off", ""):
        return False
    return default

ALERTS_ENABLED = _env_bool("ALERTS_ENABLED", True)
USE_TELEGRAM_PROXY = _env_bool("USE_TELEGRAM_PROXY", False)
SUPPRESS_PERSISTENT_ALERTS = _env_bool("SUPPRESS_PERSISTENT_ALERTS", False)
REPORT_URL = os.getenv("REPORT_URL")
PER_DOMAIN_THRESHOLD = int(os.getenv("AGGR_THRESHOLD_PER_DOMAIN", "5"))
SYSTEMIC_LANDINGS_THRESHOLD = int(os.getenv("SYSTEMIC_LANDINGS_THRESHOLD", "5"))
TIMEZONE_LABEL = os.getenv("TZ_LABEL", "MSK")
RUN_SUMMARY_ENABLED = _env_bool("RUN_SUMMARY_ENABLED", False)
# By default, send only ONE success summary message to avoid perceived duplicates.
# If you want both formats, enable the short summary explicitly.
RUN_SUMMARY_LONG_ENABLED = _env_bool("RUN_SUMMARY_LONG_ENABLED", True)
RUN_SUMMARY_SHORT_ENABLED = _env_bool("RUN_SUMMARY_SHORT_ENABLED", False)
# Управление URL-уровнем fixed-уведомлений (включено по умолчанию)
URL_FIXED_ALERTS_ENABLED = _env_bool("URL_FIXED_ALERTS_ENABLED", True)
# Repeat counter behavior
NORMALIZE_STEP_KEYS = _env_bool("NORMALIZE_STEP_KEYS", True)
SHOW_RUN_REPEAT_IN_ALERTS = _env_bool("SHOW_RUN_REPEAT_IN_ALERTS", True)
RESET_ERROR_COUNTERS_ON_START = _env_bool("RESET_ERROR_COUNTERS_ON_START", False)
try:
    TELEGRAM_PROXY_TIMEOUT_SEC = float(os.getenv("TELEGRAM_PROXY_TIMEOUT_SEC", "15"))
except Exception:
    TELEGRAM_PROXY_TIMEOUT_SEC = 15.0
try:
    PAGE_NAVIGATION_TIMEOUT_MS = int(os.getenv("PAGE_NAVIGATION_TIMEOUT_MS", "45000"))
except Exception:
    PAGE_NAVIGATION_TIMEOUT_MS = 45000
try:
    PAGE_ACTION_TIMEOUT_MS = int(os.getenv("PAGE_ACTION_TIMEOUT_MS", "30000"))
except Exception:
    PAGE_ACTION_TIMEOUT_MS = 30000
try:
    STABLE_GOTO_RETRIES = int(os.getenv("STABLE_GOTO_RETRIES", "1"))
except Exception:
    STABLE_GOTO_RETRIES = 1
try:
    STABLE_GOTO_RETRY_SLEEP_SEC = float(os.getenv("STABLE_GOTO_RETRY_SLEEP_SEC", "0.6"))
except Exception:
    STABLE_GOTO_RETRY_SLEEP_SEC = 0.6
STABLE_GOTO_ENABLED = _env_bool("STABLE_GOTO_ENABLED", True)

_PROXY_MISSING_ENV_LOGGED = False

# Default path must be writable both locally (Windows/macOS/Linux) and in CI.
# CI can override via ALERTS_STATE_PATH.
ALERTS_STATE_PATH_ENV = os.getenv("ALERTS_STATE_PATH", "alerts_state.json").strip()
_STATE_FILE = Path(ALERTS_STATE_PATH_ENV)
_STATE = {"domain_errors": {}, "systemic_errors": {}, "test_errors": {}}

def _load_state():
    global _STATE
    try:
        if _STATE_FILE.exists():
            _STATE = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _STATE = {"domain_errors": {}, "systemic_errors": {}, "test_errors": {}}


def _save_state():
    try:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        _STATE_FILE.write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


_load_state()
try:
    # Backward-compat: older state files may not have new keys.
    if not isinstance(_STATE, dict):
        _STATE = {"domain_errors": {}, "systemic_errors": {}, "test_errors": {}}
    _STATE.setdefault("domain_errors", {})
    _STATE.setdefault("systemic_errors", {})
    _STATE.setdefault("test_errors", {})
except Exception:
    pass


# ==== Run-time aggregation structures ====
RUN_TOTAL_PAGES = 0
RUN_PASSED = 0
RUN_FAILED = 0
RUN_LANDINGS = set()
PAGES_PER_DOMAIN = defaultdict(int)
DOMAIN_ERROR_COUNTS = defaultdict(int)  # key: (domain, error_key)
DOMAIN_ERROR_URLS = defaultdict(set)    # key: (domain, error_key) -> urls
ERROR_DOMAINS = defaultdict(set)        # key: error_key -> domains
# Трекинг тестов по парам (домен, шаг) и по URL для более информативных fixed-уведомлений
DOMAIN_ERROR_TESTS = defaultdict(set)   # key: (domain, error_key) -> set(test_names)
DOMAIN_ERROR_FILES = defaultdict(set)   # key: (domain, error_key) -> set(file_paths)
URL_ERROR_TESTS = defaultdict(set)      # key: url -> set(test_names)
# Отслеживание подсчёта результатов по тестам (чтобы корректно учитывать setup/teardown)
_COUNTED_NODEIDS: set[str] = set()
_PASSED_NODEIDS: set[str] = set()

# Группировка по названиям тестов (для "массовых" ошибок по конкретному кейсу)
TEST_FAIL_COUNTS = defaultdict(int)          # key: test_name -> total failed occurrences
TEST_FAIL_DOMAINS = defaultdict(set)         # key: test_name -> set(domains)
TEST_FAIL_LAST_STEP = {}                     # key: test_name -> last seen step name
TEST_FAIL_URLS = defaultdict(set)            # key: test_name -> set(urls)
TEST_NAME_FILES = defaultdict(set)           # key: test_name -> set(file_paths)

# ==== Persistent run log for daily summaries ====
# This file is json-lines (one record per line). Keep default consistent with `tools/daily_report.py`.
RUN_LOG_PATH_ENV = os.getenv("RUN_LOG_PATH", ".run_summaries.jsonl").strip()
_RUN_LOG_PATH = Path(RUN_LOG_PATH_ENV)


# ==== Persistent errors counter (external file) ====
ERRORS_COUNT_PATH_ENV = os.getenv("ERRORS_COUNT_PATH", "errors_count.json").strip()
_ERRORS_COUNT_PATH = Path(ERRORS_COUNT_PATH_ENV)
_ERRORS_COUNT = {"by_domain": {}, "by_test": {}, "total": 0, "updated_at": None}


def _load_errors_counter():
    global _ERRORS_COUNT
    try:
        if _ERRORS_COUNT_PATH.exists():
            _ERRORS_COUNT = json.loads(_ERRORS_COUNT_PATH.read_text(encoding="utf-8"))
        else:
            _save_errors_counter()
    except Exception:
        # keep in-memory defaults if file is unreadable
        _ERRORS_COUNT = {"by_domain": {}, "by_test": {}, "total": 0, "updated_at": None}


def _save_errors_counter():
    try:
        _ERRORS_COUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ERRORS_COUNT_PATH.write_text(json.dumps(_ERRORS_COUNT, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _inc_error_counter(domain: str, error_key: str) -> int:
    try:
        by_domain = _ERRORS_COUNT.setdefault("by_domain", {})
        domain_map = by_domain.setdefault(domain, {})
        domain_map[error_key] = int(domain_map.get(error_key, 0)) + 1
        _ERRORS_COUNT["total"] = int(_ERRORS_COUNT.get("total", 0)) + 1
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
        return int(domain_map.get(error_key, 0))
    except Exception:
        return 0


def _inc_url_counter(url: str | None) -> int:
    """Increment persistent counter for a specific URL, independent of step/error.
    Returns the updated count for that URL.
    """
    try:
        if not url:
            return 0
        by_url = _ERRORS_COUNT.setdefault("by_url", {})
        by_url[url] = int(by_url.get(url, 0)) + 1
        _ERRORS_COUNT["total"] = int(_ERRORS_COUNT.get("total", 0)) + 1
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
        return int(by_url.get(url, 0))
    except Exception:
        return 0


def _inc_pair_counter(domain: str | None, step: str | None) -> int:
    """Increment persistent counter for a specific (domain, step) incident across runs."""
    try:
        if not domain or not step:
            return 0
        by_pair = _ERRORS_COUNT.setdefault("by_pair", {})
        dmap = by_pair.setdefault(domain, {})
        dmap[step] = int(dmap.get(step, 0)) + 1
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
        return int(dmap.get(step, 0))
    except Exception:
        return 0


def _inc_test_counter(domain: str | None, test_name: str | None) -> int:
    """Increment persistent counter for a specific (domain, test) incident across runs."""
    try:
        if not domain or not test_name:
            return 0
        by_test = _ERRORS_COUNT.setdefault("by_test", {})
        dmap = by_test.setdefault(domain, {})
        dmap[test_name] = int(dmap.get(test_name, 0)) + 1
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
        return int(dmap.get(test_name, 0))
    except Exception:
        return 0


def _reset_test_counter(domain: str | None, test_name: str | None) -> None:
    """Reset/remove persistent error counter for a specific (domain, test)."""
    try:
        if not domain or not test_name:
            return
        by_test = _ERRORS_COUNT.setdefault("by_test", {})
        dmap = by_test.setdefault(domain, {})
        if test_name in dmap:
            try:
                del dmap[test_name]
            except Exception:
                dmap[test_name] = 0
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
    except Exception:
        pass


_load_errors_counter()

def _reset_url_counter(url: str | None) -> None:
    """Reset/remove persistent error counter for a specific URL."""
    try:
        if not url:
            return
        by_url = _ERRORS_COUNT.setdefault("by_url", {})
        if url in by_url:
            try:
                del by_url[url]
            except Exception:
                by_url[url] = 0
        _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        _save_errors_counter()
    except Exception:
        pass


def _reset_domain_url_counters(domain: str | None) -> None:
    """Reset/remove counters for all URLs that belong to the given domain (netloc match)."""
    try:
        if not domain:
            return
        by_url = _ERRORS_COUNT.setdefault("by_url", {})
        to_delete = []
        for u in list(by_url.keys()):
            try:
                if (urlparse(u).netloc or "") == domain:
                    to_delete.append(u)
            except Exception:
                continue
        for u in to_delete:
            try:
                del by_url[u]
            except Exception:
                by_url[u] = 0
        if to_delete:
            _ERRORS_COUNT["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            _save_errors_counter()
    except Exception:
        pass


# ==== Cross-worker dedup flags (to avoid duplicate alerts in parallel) ====
# Make flags run-scoped so they don't persist across builds and suppress fresh alerts
_FLAGS_BASE_DIR = Path(os.getenv("ALERTS_FLAG_DIR", ".alerts_flags"))
# Prefer explicit run id from env (e.g., Jenkins BUILD_ID, GitHub/GitLab IDs), else generate one
_RUN_ID = (
    os.getenv("ALERTS_RUN_ID")
    or os.getenv("BUILD_ID")
    or os.getenv("GITHUB_RUN_ID")
    or os.getenv("CI_PIPELINE_ID")
)
if not _RUN_ID:
    # Fallback: timestamp + pid to avoid collisions
    _RUN_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
ALERTS_FLAG_DIR = _FLAGS_BASE_DIR / _RUN_ID
try:
    ALERTS_FLAG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# Per-run worker logs (xdist): workers append failures here; master aggregates on sessionfinish.
_FAILED_TESTS_DIR = ALERTS_FLAG_DIR / "failed_tests"
try:
    _FAILED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_EXECUTED_TESTS_DIR = ALERTS_FLAG_DIR / "executed_tests"
try:
    _EXECUTED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def _reinit_flag_dir_from_env():
    """Re-initialize the flag directory based on current env (shared across xdist workers)."""
    global _FLAGS_BASE_DIR, _RUN_ID, ALERTS_FLAG_DIR
    try:
        _FLAGS_BASE_DIR = Path(os.getenv("ALERTS_FLAG_DIR", ".alerts_flags"))
        _RUN_ID = (
            os.getenv("ALERTS_RUN_ID")
            or os.getenv("BUILD_ID")
            or os.getenv("GITHUB_RUN_ID")
            or os.getenv("CI_PIPELINE_ID")
        )
        if not _RUN_ID:
            _RUN_ID = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        ALERTS_FLAG_DIR = _FLAGS_BASE_DIR / _RUN_ID
        ALERTS_FLAG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _flag_path(domain: str, error_key: str, kind: str = "single") -> Path:
    safe = slugify(f"{domain}-{error_key}") or "key"
    return ALERTS_FLAG_DIR / f"{kind}-{safe}.flag"


def _claim_flag(domain: str, error_key: str, kind: str = "single") -> bool:
    """Return True if we created the flag (first claimant), False if already exists."""
    try:
        p = _flag_path(domain, error_key, kind)
        with open(p, "x", encoding="utf-8") as _:
            _.write("1")
        return True
    except FileExistsError:
        return False
    except Exception:
        # If anything goes wrong, don't block alerts (better to duplicate than to miss).
        return True


def _pair_fail_flag_path(domain: str, error_key: str) -> Path:
    safe = slugify(f"{domain}-{error_key}") or "key"
    return ALERTS_FLAG_DIR / f"seenfail-{safe}.flag"


def _mark_pair_failed_this_run(domain: str | None, error_key: str | None) -> None:
    """Mark that (domain, step) failed somewhere in this run (xdist-safe via shared flag dir)."""
    try:
        if not domain or not error_key:
            return
        p = _pair_fail_flag_path(domain, error_key)
        try:
            with open(p, "x", encoding="utf-8") as f:
                f.write("1")
        except FileExistsError:
            return
    except Exception:
        pass


def _pair_failed_this_run(domain: str, error_key: str) -> bool:
    try:
        return _pair_fail_flag_path(domain, error_key).exists()
    except Exception:
        return False

def pytest_configure(config):
    """Ensure a shared ALERTS_RUN_ID across xdist workers and re-init flag dir."""
    try:
        # If we're a worker, master passes workerinput
        workerinput = getattr(config, "workerinput", None)
        if workerinput is not None:
            rid = workerinput.get("alerts_run_id")
            if rid:
                os.environ["ALERTS_RUN_ID"] = str(rid)
        else:
            # Master node: ensure a stable run id for all workers in this session if not provided by CI
            rid = (
                os.getenv("ALERTS_RUN_ID")
                or os.getenv("BUILD_ID")
                or os.getenv("GITHUB_RUN_ID")
                or os.getenv("CI_PIPELINE_ID")
            )
            if not rid:
                rid = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                os.environ["ALERTS_RUN_ID"] = rid
        _reinit_flag_dir_from_env()
        # Recreate per-run dirs after reinit (important for xdist workers)
        try:
            global _FAILED_TESTS_DIR
            _FAILED_TESTS_DIR = ALERTS_FLAG_DIR / "failed_tests"
            _FAILED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            global _EXECUTED_TESTS_DIR
            _EXECUTED_TESTS_DIR = ALERTS_FLAG_DIR / "executed_tests"
            _EXECUTED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Optional: reset persistent counters once per run (master only)
        try:
            if RESET_ERROR_COUNTERS_ON_START and getattr(config, "workerinput", None) is None:
                # run-scoped flag to avoid multiple resets
                reset_flag = ALERTS_FLAG_DIR / "reset-counters.flag"
                try:
                    with open(reset_flag, "x", encoding="utf-8") as f:
                        f.write("1")
                    _ERRORS_COUNT.clear()
                    _ERRORS_COUNT.update({"by_domain": {}, "by_url": {}, "by_pair": {}, "by_test": {}, "total": 0, "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")})
                    _save_errors_counter()
                except FileExistsError:
                    pass
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def pytest_configure_node(node):
    """Propagate ALERTS_RUN_ID from master to each xdist worker."""
    try:
        rid = (
            os.getenv("ALERTS_RUN_ID")
            or os.getenv("BUILD_ID")
            or os.getenv("GITHUB_RUN_ID")
            or os.getenv("CI_PIPELINE_ID")
        )
        if not rid:
            rid = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            os.environ["ALERTS_RUN_ID"] = rid
        node.workerinput["alerts_run_id"] = rid
    except Exception:
        pass


def _get_test_counter(domain: str | None, test_name: str | None) -> int:
    """Get current persistent counter for a specific (domain, test)."""
    try:
        if not domain or not test_name:
            return 0
        by_test = _ERRORS_COUNT.get("by_test", {}) or {}
        dmap = by_test.get(domain, {}) or {}
        return int(dmap.get(test_name, 0))
    except Exception:
        return 0


def _test_id(item) -> str:
    """Unique test id for alerting/counters. Use nodeid to avoid collisions across same allure.title."""
    try:
        return str(getattr(item, "nodeid", "") or getattr(item, "name", "") or "")
    except Exception:
        return ""


def _test_display_name(item, form_title: str | None) -> str:
    """Human-friendly name for messages/sheets."""
    try:
        return str(form_title or getattr(item, "name", None) or getattr(item, "nodeid", None) or "—")
    except Exception:
        return str(form_title or "—")


def _short_id(text: str, n: int = 8) -> str:
    try:
        return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:n]
    except Exception:
        return "id"


def _safe_flag_key(domain: str, name: str) -> str:
    """Generate a short filesystem-friendly key (avoid very long filenames from test titles)."""
    try:
        base = slugify(f"{domain}-{name}") or "key"
        base = base[:80]
        h = hashlib.md5(f"{domain}|{name}".encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        return f"{base}-{h}"
    except Exception:
        return slugify(f"{domain}-{name}") or "key"


def _worker_id() -> str:
    try:
        return os.getenv("PYTEST_XDIST_WORKER") or "master"
    except Exception:
        return "master"


def _append_failed_test_record(domain: str, test_name: str, *, url: str | None, last_step: str | None, details: str | None) -> None:
    """Append one failure record for this run (worker-safe). Master later aggregates for fixed logic."""
    try:
        rec = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "domain": domain,
            "test": test_name,
            "url": url or "",
            "step": last_step or "",
            "details": (_sanitize_error_text(details) or "")[:2000],
            "worker": _worker_id(),
        }
        p = _FAILED_TESTS_DIR / f"{_worker_id()}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_executed_test_record(domain: str, test_name: str, *, url: str | None) -> None:
    """Record that (domain, test) was actually executed in this run (for correct fixed logic)."""
    try:
        rec = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "domain": domain,
            "test": test_name,
            "url": url or "",
            "worker": _worker_id(),
        }
        p = _EXECUTED_TESTS_DIR / f"{_worker_id()}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _test_fail_flag_path(domain: str, test_name: str) -> Path:
    safe = _safe_flag_key(domain, test_name)
    return ALERTS_FLAG_DIR / f"seenfailtest-{safe}.flag"


def _mark_test_failed_this_run(domain: str | None, test_name: str | None) -> None:
    """Mark that (domain, test) failed somewhere in this run (xdist-safe via shared flag dir)."""
    try:
        if not domain or not test_name:
            return
        p = _test_fail_flag_path(domain, test_name)
        try:
            with open(p, "x", encoding="utf-8") as f:
                f.write("1")
        except FileExistsError:
            return
    except Exception:
        pass


def _test_failed_this_run(domain: str, test_name: str) -> bool:
    try:
        return _test_fail_flag_path(domain, test_name).exists()
    except Exception:
        return False


def _now_str():
    """Return current time string adjusted to configured timezone.
    By default, if TZ_LABEL=MSK, we shift UTC by +3 hours; otherwise use TZ_OFFSET_HOURS if provided.
    """
    try:
        from datetime import timedelta
        # If explicit offset provided, use it; else default to +3 for MSK, 0 otherwise.
        default_offset = "3" if (str(TIMEZONE_LABEL).upper() == "MSK") else "0"
        offset_hours = int(os.getenv("TZ_OFFSET_HOURS", default_offset))
        ts = datetime.utcnow() + timedelta(hours=offset_hours)
        return ts.strftime("%Y-%m-%d %H:%M") + f" ({TIMEZONE_LABEL})"
    except Exception:
        return f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE_LABEL})"


def _utc_iso() -> str:
    try:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""

# ==== Error text sanitization ====
def _sanitize_error_text(text: str | None) -> str | None:
    """Remove internal technical suffixes from human-facing error messages."""
    if not text:
        return text
    try:
        # Cut off everything starting from the technical-details marker
        cleaned = str(text).split("Технические детали:", 1)[0].rstrip()
        return cleaned
    except Exception:
        return text


def _normalize_step_key(step_name: str | None) -> str | None:
    """
    Делает ключ шага стабильным для счётчиков.
    Примеры:
    - "Кнопка #2" -> "Кнопка #N"
    - "Открыть город: Майкоп (idx 178) ..." -> "Открыть город: Майкоп (idx N) ..."
    """
    if not step_name:
        return step_name
    try:
        s = str(step_name)
        # normalize common dynamic suffixes
        s = re.sub(r"#\s*\d+", "#N", s)
        s = re.sub(r"\bidx\s*\d+\b", "idx N", s, flags=re.IGNORECASE)
        s = re.sub(r"\bid\s*\d+\b", "id N", s, flags=re.IGNORECASE)
        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s
    except Exception:
        return step_name

# ==== URL extraction from Playwright error text ====
_ERR_URL_RE = re.compile(r"https?://[^\s\"')]+")

def _extract_url_from_error_text(text: str | None) -> str | None:
    """Try to extract the most relevant URL from Playwright error messages.
    Useful when the test runs on one landing, but fails navigating to a different URL.
    """
    if not text:
        return None
    try:
        matches = _ERR_URL_RE.findall(str(text))
        if not matches:
            return None
        # Prefer the last mentioned URL (often the actual navigation target in call log).
        return matches[-1]
    except Exception:
        return None

# ==== Google Sheets error logging (optional) ====
_GS_CLIENT = None
_GS_WORKSHEET = None
ERROR_LOGGED_NODEIDS: set[str] = set()

def _ensure_gsheets():
    """Initialize gspread client and worksheet if env config present."""
    global _GS_CLIENT, _GS_WORKSHEET
    if _GS_WORKSHEET is not None:
        return True
    try:
        sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        spreadsheet_id = os.getenv("SPREADSHEET_ID")
        ws_title = os.getenv("GOOGLE_SHEETS_WORKSHEET", "Sheet1")
        if not sa_path or not spreadsheet_id:
            return False
        client = gspread.service_account(filename=sa_path)
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet(ws_title)
        _GS_CLIENT = client
        _GS_WORKSHEET = ws
        return True
    except Exception:
        _GS_CLIENT = None
        _GS_WORKSHEET = None
        return False

def _now_msk_str() -> str:
    # Russia (Moscow) is UTC+3 year-round
    try:
        from datetime import timedelta
        utc = datetime.utcnow()
        msk = utc + timedelta(hours=3)
        return msk.strftime("%Y-%m-%d %H:%M") + " (MSK)"
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M") + " (MSK)"

def _append_error_row(url: str | None, test_name: str, error_text: str, repeat_count: int | None = None, status: str = "failed"):
    """Append a single row to the configured Google Sheet.
    Columns: URL, Test Name, Error, Repeat, Timestamp, Status
    """
    try:
        if not _ensure_gsheets():
            return
        ts = _now_msk_str()
        repeat_str = "" if repeat_count is None else str(repeat_count)
        row = [
            url or "",
            test_name or "",
            (_sanitize_error_text(error_text) or "").strip(),
            repeat_str,
            ts,
            (status or "").strip(),
        ]
        _GS_WORKSHEET.append_row(row, value_input_option="RAW")
    except Exception:
        # Do not let Sheets errors break test run
        pass


def _should_notify_persistent(count: int) -> bool:
    # 1-й, 4-й, 10-й, далее каждые 10 (20, 30, 40, ...)
    if count in (1, 4, 10):
        return True
    if count >= 10 and count % 10 == 0:
        return True
    return False


def _get_domain(url: str | None) -> str | None:
    try:
        if not url:
            return None
        return urlparse(url).netloc or None
    except Exception:
        return None


def _get_last_step_name() -> str | None:
    try:
        return getattr(_TLS, "last_step_name", None)
    except Exception:
        return None


def _get_proxy_transport_env() -> tuple[str, str, str] | None:
    global _PROXY_MISSING_ENV_LOGGED

    proxy_url = (os.getenv("TELEGRAM_PROXY_URL") or "").strip()
    auth_secret = (os.getenv("TELEGRAM_PROXY_AUTH_SECRET") or "").strip()
    creds = (os.getenv("TELEGRAM_PROXY_CREDS") or "").strip()

    missing = []
    if not proxy_url:
        missing.append("TELEGRAM_PROXY_URL")
    if not auth_secret:
        missing.append("TELEGRAM_PROXY_AUTH_SECRET")
    if not creds:
        missing.append("TELEGRAM_PROXY_CREDS")

    if missing:
        if not _PROXY_MISSING_ENV_LOGGED:
            print(f"[TELEGRAM][proxy] Missing required env vars: {', '.join(missing)}")
            _PROXY_MISSING_ENV_LOGGED = True
        return None
    return proxy_url, auth_secret, creds


def _send_telegram_message_direct(text: str) -> None:
    try:
        if not bot or not chat_id:
            return
        bot.send_message(chat_id, text)
    except Exception:
        pass


def _send_telegram_message_via_proxy(text: str) -> None:
    proxy_env = _get_proxy_transport_env()
    if not proxy_env:
        return

    proxy_url, auth_secret, creds = proxy_env
    try:
        response = requests.post(
            proxy_url,
            headers={
                "Content-Type": "application/json",
                "X-Authentication": auth_secret,
            },
            json={
                "title": html.escape("Runtime alert"),
                "text": html.escape(text),
                "creds": creds,
                "parse_mode": "HTML",
                "disable_notification": False,
            },
            timeout=TELEGRAM_PROXY_TIMEOUT_SEC,
        )
    except requests.Timeout:
        print(f"[TELEGRAM][proxy] Request timeout after {TELEGRAM_PROXY_TIMEOUT_SEC}s")
        return
    except requests.RequestException as exc:
        print(f"[TELEGRAM][proxy] Transport error: {exc}")
        return
    except Exception as exc:
        print(f"[TELEGRAM][proxy] Unexpected error: {exc}")
        return

    if 200 <= response.status_code < 300:
        return

    body = (response.text or "").strip().replace("\n", " ")
    print(f"[TELEGRAM][proxy] Request failed (status={response.status_code}): {body[:180]}")


def _send_telegram_message(text: str) -> None:
    if not ALERTS_ENABLED:
        return
    if USE_TELEGRAM_PROXY:
        _send_telegram_message_via_proxy(text)
    else:
        _send_telegram_message_direct(text)


def _format_single_error_message(form_title: str | None, url: str | None, step_name: str | None, details: str | None) -> str:
    domain = _get_domain(url) or "—"
    form_part = form_title or ""
    msg = []
    msg.append(f"🚨 Ошибка автотеста формы {f'[{form_part}]' if form_part else ''}")
    msg.append("")
    msg.append(f"🕒 Время: {_now_str()}")
    msg.append(f"🌐 Лендинг: {domain}")
    if url:
        msg.append(f"🔗 URL: {url}")
    if step_name:
        msg.append(f"❌ Ошибка: Не выполнен шаг \"{step_name}\"")
    if details:
        msg.append(f"🔎 Детали: {details}")
    if REPORT_URL:
        msg.append(f"🔎 Отчёт: {REPORT_URL}")
    return "\n".join(msg)


def _format_persistent_error_message(
    form_title: str | None,
    url: str | None,
    step_name: str | None,
    details: str | None,
    domain: str,
    error_key: str,
    repeats_count: int,
    test_name: str | None,
    *,
    run_repeats: int | None = None,
) -> str:
    form_part = form_title or ""
    # Prefer deriving the landing from the actual incident URL shown in the message
    domain_for_msg = _get_domain(url) or (domain or "—")
    msg = []
    msg.append(f"🚨 Ошибка автотеста формы {f'[{form_part}]' if form_part else ''}")
    msg.append("")
    msg.append(f"🕒 Время: {_now_str()}")
    msg.append(f"🌐 Лендинг: {domain_for_msg}")
    if url:
        msg.append(f"🔗 URL: {url}")
    if test_name:
        msg.append(f"🧪 Тест: {test_name}")
    msg.append(f"❌ Ошибка: Не выполнен шаг \"{step_name or error_key}\"")
    if details:
        msg.append(f"🔎 Детали: {details}")
    if SHOW_RUN_REPEAT_IN_ALERTS and run_repeats is not None:
        msg.append(f"🔁 Повтор (в этом прогоне): {run_repeats}")
    msg.append(f"🔁 Повтор (накопительно): {repeats_count}")
    if REPORT_URL:
        msg.append(f"🔎 Отчёт: {REPORT_URL}")
    return "\n".join(msg)


def _format_persistent_test_message(
    form_title: str | None,
    url: str | None,
    test_name: str,
    details: str | None,
    domain: str,
    repeats_count: int,
    *,
    last_step: str | None = None,
    run_repeats: int | None = None,
) -> str:
    """Persistent failure message keyed by TEST (not by step)."""
    form_part = form_title or ""
    domain_for_msg = _get_domain(url) or (domain or "—")
    msg: list[str] = []
    msg.append(f"🚨 Ошибка автотеста формы {f'[{form_part}]' if form_part else ''}")
    msg.append("")
    msg.append(f"🕒 Время: {_now_str()}")
    # Show the failing URL (more useful than just the landing domain).
    if url:
        msg.append(f"🌐 URL: {url}")
    else:
        msg.append(f"🌐 Лендинг: {domain_for_msg}")
    msg.append(f"🧪 Тест: {test_name}")
    if last_step:
        msg.append(f"❌ Ошибка: Не выполнен шаг \"{last_step}\"")
    if details:
        msg.append(f"🔎 Детали: {details}")
    msg.append(f"🔁 Повтор (накопительно): {repeats_count}")
    if REPORT_URL:
        msg.append(f"🔎 Отчёт: {REPORT_URL}")
    return "\n".join(msg)


def _format_fixed_test_message(
    domain: str,
    test_name: str,
    sample_url: str | None = None,
    *,
    form_title: str | None = None,
    last_step: str | None = None,
) -> str:
    form_part = form_title or test_name or ""
    msg: list[str] = []
    if last_step:
        msg.append(f"✅ Ошибка автотеста формы {f'[{form_part}]' if form_part else ''} исправлена (шаг \"{last_step}\")")
    else:
        msg.append(f"✅ Ошибка автотеста формы {f'[{form_part}]' if form_part else ''} исправлена")
    msg.append("")
    msg.append(f"🕒 Время: {_now_str()}")
    if sample_url:
        msg.append(f"🌐 URL: {sample_url}")
    else:
        msg.append(f"🌐 Лендинг: {domain}")
    if REPORT_URL:
        msg.append(f"🔎 Отчёт: {REPORT_URL}")
    return "\n".join(msg)


def _format_persistent_url_message(form_title: str | None, url: str | None, repeats_count: int, test_name: str | None, details: str | None) -> str:
    domain = _get_domain(url) or "—"
    form_part = form_title or ""
    msg = []
    msg.append(f"🚨 Ошибка автотеста формы {f'[{form_part}]' if form_part else ''}")
    msg.append("")
    msg.append(f"🕒 Время: {_now_str()}")
    msg.append(f"🌐 Лендинг: {domain}")
    if url:
        msg.append(f"🔗 URL: {url}")
    if test_name:
        msg.append(f"🧪 Тест: {test_name}")
    if details:
        msg.append(f"🔎 Детали: {details}")
    msg.append(f"🔁 Повтор: {repeats_count}")
    if REPORT_URL:
        msg.append(f"🔎 Отчёт: {REPORT_URL}")
    return "\n".join(msg)


# Удалены все функции и сообщения, связанные с массовыми/агрегированными оповещениями


def _format_run_summary() -> str:
    success = RUN_PASSED
    errors = RUN_FAILED
    total = RUN_TOTAL_PAGES
    pct = int(round((success / total) * 100)) if total else 0
    msg = []
    msg.append(f"✅ Автотест завершён ({_now_str()})")
    msg.append("")
    msg.append(f"🌐 Лендингов проверено: {len(RUN_LANDINGS)}")
    msg.append(f"🔗 Страниц: {total}")
    msg.append(f"✔️ Успешных: {success} ({pct}%)")
    msg.append(f"❌ Ошибок: {errors} ({100 - pct if total else 0}%)")
    if REPORT_URL:
        msg.append(f"📊 Детали: {REPORT_URL}")
    return "\n".join(msg)

def _format_short_run_summary() -> str:
    """Короткая сводка: Успешно / Неуспешно / Всего / Прогонов."""
    success = RUN_PASSED
    errors = RUN_FAILED
    total = RUN_TOTAL_PAGES
    runs = success + errors
    # Заголовок: текущая дата UTC (или локальная, если потребуется — можно расширить)
    today_ymd = datetime.utcnow().strftime("%Y-%m-%d")
    last_run_hhmm = datetime.utcnow().strftime("%d.%m.%Y %H:%M")
    parts = []
    parts.append(f"📊 Отчёт за {today_ymd}")
    parts.append("")
    parts.append(f"Сводка: успешно {success}, неуспешно {errors}")
    parts.append("")
    parts.append(f"Всего страниц: {total}")
    parts.append(f"Прогонов: {runs}")
    parts.append("")
    parts.append(f"Последний запуск: {last_run_hhmm}")
    if REPORT_URL:
        parts.append(f"📊 Детали: {REPORT_URL}")
    return "\n\n".join(parts)

def extract_run_labels(session, stats) -> list:
    """Возвращает список названий папок запуска (например, test_beeline),
    определённых по аргументам запуска pytest и/или по путям тестов из отчётов."""
    labels = set()
    try:
        root = str(session.config.rootpath)
        args = getattr(session.config, 'args', None) or []
        for arg in args:
            ap = os.path.abspath(arg)
            if not os.path.exists(ap):
                ap2 = os.path.abspath(os.path.join(root, arg))
                ap = ap2 if os.path.exists(ap2) else ap
            if not os.path.exists(ap):
                continue
            rel = os.path.relpath(ap, root)
            parts = rel.replace('\\', '/').split('/')
            if parts and parts[0] == 'tests' and len(parts) > 1:
                labels.add(parts[1])
            elif parts:
                labels.add(parts[0])
    except Exception:
        pass

    if not labels:
        try:
            for key, reports in (stats or {}).items():
                for report in reports:
                    if getattr(report, 'when', 'call') != 'call':
                        continue
                    path = report.nodeid.split('::', 1)[0]
                    parts = path.split('/')
                    if 'tests' in parts:
                        idx = parts.index('tests')
                        if idx is not None and len(parts) > idx + 1:
                            labels.add(parts[idx + 1])
        except Exception:
            pass

    return sorted(labels)


def check_page_status_code(page, url):
    """
    Проверяет статус код страницы и добавляет информацию в Allure отчет
    """
    try:
        # Получаем все ответы для данного URL
        responses = []
        for response_obj in page.context.request.all():
            if url in response_obj.url:
                responses.append(response_obj)
        
        if responses:
            # Берем последний ответ для основного URL
            main_response = responses[-1]
            status_code = main_response.status
            
            with allure.step(f"Проверка статус кода для {url}"):
                allure.attach(
                    f"URL: {url}\nСтатус код: {status_code}",
                    name="Статус код страницы",
                    attachment_type=allure.attachment_type.TEXT
                )
                
                if status_code >= 400:
                    allure.attach(
                        f"Ошибка HTTP: {status_code}\nURL: {url}",
                        name="Ошибка HTTP",
                        attachment_type=allure.attachment_type.TEXT
                    )
                    return False, status_code
                return True, status_code
        else:
            with allure.step(f"Не удалось получить статус код для {url}"):
                allure.attach(
                    f"URL: {url}\nПричина: Нет ответов от сервера",
                    name="Ошибка получения статус кода",
                    attachment_type=allure.attachment_type.TEXT
                )
                return False, None
                
    except Exception as e:
        with allure.step(f"Ошибка при проверке статус кода для {url}"):
            allure.attach(
                f"URL: {url}\nОшибка: {str(e)}",
                name="Исключение при проверке статус кода",
                attachment_type=allure.attachment_type.TEXT
            )
            return False, None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    """
    Хук для перехвата ошибок и добавления информации о статус коде в Allure отчет
    """
    # If the test is marked as skipped, it must never be treated as a failure for alerts/sheets/counters.
    # This also prevents "last_step" leakage from previous tests in the same worker thread.
    try:
        if getattr(item, "get_closest_marker", None) is not None:
            if item.get_closest_marker("skip") is not None:
                return
    except Exception:
        pass
    # Фиксируем метаданные для тестов: на падениях (любой стадии) и на успешном выполнении call-этапа
    if (call.excinfo is not None and call.when in ("call", "setup", "teardown")) or (call.excinfo is None and call.when == "call"):
        try:
            # Извлекаем allure.title, если указан декоратором
            title = None
            # Варианты хранения заголовка в объекте теста
            for attr_name in (
                "__allure_display_name__",
                "__allure_title__",
                "allure_title",
                "allure_display_name",
            ):
                title = getattr(getattr(item, "obj", None) or getattr(item, "function", None), attr_name, None)
                if isinstance(title, str) and title.strip():
                    break

            # Попытка достать из маркеров (иногда хранится как маркер)
            if not title:
                try:
                    marker = next(item.iter_markers(name="allure_title"), None)
                    if marker and marker.args:
                        title = str(marker.args[0])
                except Exception:
                    pass

            # Извлекаем allure.description, если есть
            description = None
            for attr_name in (
                "__allure_description__",
                "allure_description",
                "description",
            ):
                description = getattr(getattr(item, "obj", None) or getattr(item, "function", None), attr_name, None)
                if isinstance(description, str) and description.strip():
                    break
            if not description:
                try:
                    marker = next(item.iter_markers(name="allure_description"), None)
                    if marker and marker.args:
                        description = str(marker.args[0])
                except Exception:
                    pass

            # Извлекаем URL: сначала пробуем найти в маркерах allure.feature (или других) строку, похожую на URL
            feature_url = None
            try:
                for m in item.iter_markers():
                    # Собираем все значения аргументов и kwargs
                    values = []
                    try:
                        values.extend(list(m.args))
                    except Exception:
                        pass
                    try:
                        values.extend(list(m.kwargs.values()))
                    except Exception:
                        pass
                    for v in values:
                        if isinstance(v, str) and v.startswith("http"):
                            feature_url = v
                            break
                    if feature_url:
                        break
            except Exception:
                pass

            # Фолбэк: берем первый параметр-URL из funcargs
            if not feature_url:
                try:
                    for k, v in (item.funcargs or {}).items():
                        if isinstance(v, str) and v.startswith("http"):
                            feature_url = v
                            break
                except Exception:
                    pass

            # Сохраняем мета в глобальном словаре для последующего отчета
            TEST_META[item.nodeid] = {
                "title": title,
                "description": description,
                "feature_url": feature_url,
                "when": call.when,
            }
        except Exception:
            # Не мешаем основному ходу, если метаданные не удалось собрать
            pass

    # IMPORTANT: pytest "skip" is not a failure.
    # If a test is skipped (via @pytest.mark.skip, pytest.skip in fixtures, etc),
    # do not treat it as failed for counters/alerts/Google Sheets logging.
    try:
        if call.excinfo is not None:
            try:
                skip_exc = getattr(getattr(pytest, "skip", None), "Exception", None)
                if skip_exc is not None and call.excinfo.errisinstance(skip_exc):
                    return
            except Exception:
                # Fallback: be conservative if we can't introspect the exception type
                tname = ""
                try:
                    tname = str(getattr(call.excinfo, "typename", "") or "")
                except Exception:
                    tname = ""
                if tname == "Skipped":
                    return
    except Exception:
        pass

    # Update counters and possibly send immediate alerts on failure
    try:
        current_url = None
        funcargs = (item.funcargs or {})
        # IMPORTANT: prefer the URL parameter of the test (the one passed to page.goto),
        # because page.url can change after redirects / "thank you" flows and end up as just the landing.
        param_url = None
        try:
            preferred_keys = [
                # common names across suites
                "business_url",
                "business_url_second",
                "example_url",
                "connection_url",
                "connect_cards_url",
                "checkaddress_url",
                "checkaddress_button_url",
                "checkaddress_urls",
                "undecided_url",
                "moving_url",
                "express_url",
            ]

            # Collect ALL candidate URLs from funcargs and pick the most specific one.
            # We prefer:
            # - known preferred keys
            # - keys containing "url"
            # - URLs that have a non-root path and/or query (more specific than just landing "/")
            # - longer URLs (often include city/path)
            candidates: list[tuple[str, str]] = []
            for k, v in funcargs.items():
                if isinstance(v, str) and v.startswith("http"):
                    candidates.append((str(k), v))

            def _url_score(key: str, url: str) -> int:
                score = 0
                kl = (key or "").lower()
                if key in preferred_keys:
                    score += 1000
                if "url" in kl:
                    score += 200
                try:
                    p = urlparse(url)
                    # penalize bare landing "/" and reward more specific paths
                    if (p.path or "") not in ("", "/"):
                        score += 150
                    if p.query:
                        score += 20
                except Exception:
                    pass
                score += min(len(url), 300)  # tie-breaker: longer tends to be more specific
                return score

            if candidates:
                param_url = max(candidates, key=lambda kv: _url_score(kv[0], kv[1]))[1]
        except Exception:
            param_url = None

        page_url = None
        # Live Playwright page URL if available (can be helpful if test didn't take URL params).
        try:
            page_obj = None
            for key in ("page", "page_fixture", "page_fixture_ignore_https"):
                v = funcargs.get(key)
                if v is not None:
                    page_obj = v
                    break
            if page_obj is None:
                # Fallback: any arg that looks like a Playwright Page (duck-typing).
                for _, v in funcargs.items():
                    if v is None:
                        continue
                    if hasattr(v, "locator") and hasattr(v, "goto") and hasattr(v, "url"):
                        page_obj = v
                        break
            if page_obj is not None:
                u = getattr(page_obj, "url", None)
                if isinstance(u, str) and u.startswith("http"):
                    page_url = u
        except Exception:
            page_url = None

        def _best_context_url(*vals: str | None) -> str | None:
            """Pick the most specific URL among candidates (prefer non-root path / query)."""
            try:
                candidates = [v for v in vals if isinstance(v, str) and v.startswith("http")]
                if not candidates:
                    return None

                def _score(u: str) -> int:
                    score = 0
                    try:
                        p = urlparse(u)
                        if (p.path or "") not in ("", "/"):
                            score += 150
                        if p.query:
                            score += 20
                    except Exception:
                        pass
                    score += min(len(u), 300)
                    return score

                return max(candidates, key=_score)
            except Exception:
                # Fallback to first non-empty
                for v in vals:
                    if isinstance(v, str) and v.startswith("http"):
                        return v
                return None

        # Prefer the most specific URL: sometimes the test param is just a base domain,
        # while page.url contains a city/path (more useful for alerts).
        current_url = _best_context_url(param_url, page_url)
        domain = _get_domain(current_url)

        form_title = None
        feature_url_meta = None
        try:
            meta = TEST_META.get(item.nodeid) or {}
            form_title = meta.get("title")
            feature_url_meta = meta.get("feature_url")
        except Exception:
            pass
        # Prefer live/param URL; if absent, fall back to feature_url captured from markers
        url_for_log = current_url or feature_url_meta

        # Handle skipped tests: do not log to Google Sheets; exit early without touching counters
        try:
            if call.excinfo is not None:
                typename = getattr(getattr(call, "excinfo", None), "typename", "") or ""
                if typename.lower() == "skipped":
                    return
        except Exception:
            pass

        if call.when == "call":
            global RUN_TOTAL_PAGES, RUN_PASSED, RUN_FAILED
            if item.nodeid not in _COUNTED_NODEIDS:
                RUN_TOTAL_PAGES += 1
                _COUNTED_NODEIDS.add(item.nodeid)
            if domain:
                RUN_LANDINGS.add(domain)
                PAGES_PER_DOMAIN[domain] += 1
            if call.excinfo is None:
                if item.nodeid not in _PASSED_NODEIDS:
                    RUN_PASSED += 1
                    _PASSED_NODEIDS.add(item.nodeid)
                    # FIXED по тесту отправляем только в конце прогона (pytest_sessionfinish),
                    # чтобы не было ложных "упал -> сразу исправился" при параметризации/параллели.
                    try:
                        # Mark executed (pass) for correct fixed logic in master
                        _append_executed_test_record(domain or "—", _test_id(item) or item.nodeid, url=current_url or url_for_log)
                    except Exception:
                        pass
            else:
                # Если ранее считали как passed на call-этапе, корректируем
                if item.nodeid in _PASSED_NODEIDS:
                    RUN_PASSED = max(0, RUN_PASSED - 1)
                    _PASSED_NODEIDS.discard(item.nodeid)
                # Учитываем фейл
                RUN_FAILED += 1
                step_name = _get_last_step_name() or ""
                error_key_raw = step_name or type(call.excinfo.value).__name__
                error_key = _normalize_step_key(error_key_raw) if NORMALIZE_STEP_KEYS else error_key_raw
                # Если в тексте ошибки есть конкретный URL (например, Page.goto ... at https://...),
                # используем его в сообщениях/табличке вместо URL прогона (лендинга).
                err_raw = str(call.excinfo.value) if call.excinfo else ""
                err_url = _extract_url_from_error_text(err_raw)
                # Prefer URL from error text (often the real failing navigation target),
                # else use the test URL (param/page), else marker URL.
                incident_url = err_url or current_url or url_for_log
                # If the failure is about navigating to another URL, show/aggregate by that domain in alerts.
                alert_domain = _get_domain(incident_url) or (domain or "—")
                dom_key = (alert_domain, error_key)
                DOMAIN_ERROR_COUNTS[dom_key] += 1
                # ВАЖНО: сначала узнаём, был ли инцидент активным ДО текущего падения
                was_active = False
                try:
                    was_active = bool(_STATE.get("domain_errors", {}).get(alert_domain, {}).get(error_key, {}).get("active"))
                except Exception:
                    was_active = False
                if incident_url:
                    DOMAIN_ERROR_URLS[dom_key].add(incident_url)
                # Отметить, что пара (домен, шаг) падала в этом прогоне (для корректных fixed в конце прогона при xdist)
                try:
                    _mark_pair_failed_this_run(alert_domain, error_key)
                except Exception:
                    pass
                ERROR_DOMAINS[error_key].add(alert_domain)
                # Привяжем тест к паре (домен, шаг) и к URL
                try:
                    test_display_name = None
                    file_path = ""
                    try:
                        meta = TEST_META.get(item.nodeid) or {}
                        test_display_name = meta.get("title") or getattr(item, "name", None) or item.nodeid
                        file_path = str(getattr(item, "fspath", "") or "")
                    except Exception:
                        test_display_name = getattr(item, "name", None) or item.nodeid
                        try:
                            file_path = str(getattr(item, "fspath", "") or "")
                        except Exception:
                            file_path = ""
                    if test_display_name:
                        DOMAIN_ERROR_TESTS[dom_key].add(test_display_name)
                        if file_path:
                            DOMAIN_ERROR_FILES[dom_key].add(file_path)
                            TEST_NAME_FILES[test_display_name].add(file_path)
                        if incident_url:
                            URL_ERROR_TESTS[incident_url].add(test_display_name)
                except Exception:
                    pass

                # Агрегация по названию теста
                try:
                    test_display_name = None
                    file_path = ""
                    try:
                        meta = TEST_META.get(item.nodeid) or {}
                        test_display_name = meta.get("title") or getattr(item, "name", None) or item.nodeid
                        file_path = str(getattr(item, "fspath", "") or "")
                    except Exception:
                        test_display_name = getattr(item, "name", None) or item.nodeid
                        try:
                            file_path = str(getattr(item, "fspath", "") or "")
                        except Exception:
                            file_path = ""
                    if test_display_name:
                        TEST_FAIL_COUNTS[test_display_name] += 1
                        if domain:
                            TEST_FAIL_DOMAINS[test_display_name].add(domain)
                        if step_name:
                            TEST_FAIL_LAST_STEP[test_display_name] = step_name
                        if incident_url:
                            TEST_FAIL_URLS[test_display_name].add(incident_url)
                        if file_path:
                            TEST_NAME_FILES[test_display_name].add(file_path)
                except Exception:
                    pass

                # Persistent counters:
                # - URL counter: как часто падал конкретный URL (опционально)
                # - Test counter: как часто падал конкретный тест на домене (основная логика алертов)
                new_count = _inc_url_counter(incident_url)
                test_key_id = _test_id(item) or (test_display_name or form_title or item.nodeid)
                test_disp = _test_display_name(item, form_title)
                test_repeats = _inc_test_counter(alert_domain, test_key_id)

                # Запись в Google Sheets (одна строка на тестовый пример / nodeid), с указанием номера повтора
                try:
                    if item.nodeid not in ERROR_LOGGED_NODEIDS:
                        test_name_for_log = None
                        try:
                            meta = TEST_META.get(item.nodeid) or {}
                            test_name_for_log = meta.get("title") or getattr(item, "name", None) or item.nodeid
                        except Exception:
                            test_name_for_log = getattr(item, "name", None) or item.nodeid
                        # В отчёте/таблице "повтор" логичнее вести по паре (домен, шаг),
                        # иначе при смене URL счётчик выглядит "сломано".
                        repeat_val = test_repeats if incident_url else None
                        sheet_name = f"{(test_name_for_log or test_disp)} [{_short_id(test_key_id)}]"
                        _append_error_row(incident_url or url_for_log, sheet_name, _sanitize_error_text(str(call.excinfo.value)) if call.excinfo else "", repeat_val)
                        ERROR_LOGGED_NODEIDS.add(item.nodeid)
                except Exception:
                    pass
                # Отправляем негативный алерт по расписанию (1,4,10,20,...) для ТЕСТА.
                try:
                    test_key_name = test_key_id
                    # отметим, что этот тест падал в этом прогоне (для корректного fixed в конце прогона)
                    _mark_test_failed_this_run(alert_domain, test_key_name)
                    _append_executed_test_record(alert_domain, test_key_name, url=incident_url or url_for_log)
                    _append_failed_test_record(
                        alert_domain,
                        test_key_name,
                        url=incident_url or url_for_log,
                        last_step=step_name or error_key_raw,
                        details=str(call.excinfo.value) if call.excinfo else None,
                    )
                except Exception:
                    test_key_name = test_key_id

                if (not SUPPRESS_PERSISTENT_ALERTS) and _should_notify_persistent(int(test_repeats)):
                    try:
                        if _claim_flag(alert_domain, f"test-{_safe_flag_key(alert_domain, test_key_name)}-{int(test_repeats)}", kind="persist_test"):
                            details = _sanitize_error_text(str(call.excinfo.value)) if call.excinfo else None
                            text = _format_persistent_test_message(
                                form_title=form_title,
                                url=incident_url or url_for_log,
                                test_name=test_disp,
                                details=details,
                                domain=alert_domain,
                                repeats_count=int(test_repeats),
                                last_step=step_name or error_key_raw,
                            )
                            _send_telegram_message(text)
                    except Exception:
                        pass

                # Теперь помечаем тест активным (для последующего "fixed")
                try:
                    test_ent = _STATE.setdefault("test_errors", {}).setdefault(alert_domain, {}).setdefault(test_key_name, {})
                    test_ent["active"] = True
                    test_ent["last_failed_at"] = _utc_iso()
                    test_ent["last_step"] = step_name or error_key_raw
                    test_ent["display_name"] = test_disp
                    if incident_url or url_for_log:
                        urls = test_ent.setdefault("urls", [])
                        if isinstance(urls, list):
                            u = incident_url or url_for_log
                            if u and u not in urls:
                                urls.append(u)
                            test_ent["urls"] = urls[-50:]
                except Exception:
                    pass
        elif call.excinfo is not None and call.when in ("setup", "teardown"):
            # Count failures that happen outside the 'call' phase as well
            # Корректируем счетчики: если тест ранее помечен как passed — переведем в failed,
            # если еще не считали этот тест — добавим как один проваленный прогон.
            try:
                if item.nodeid in _PASSED_NODEIDS:
                    RUN_PASSED = max(0, RUN_PASSED - 1)
                    _PASSED_NODEIDS.discard(item.nodeid)
                    RUN_FAILED += 1
                elif item.nodeid not in _COUNTED_NODEIDS:
                    RUN_TOTAL_PAGES += 1
                    RUN_FAILED += 1
                    _COUNTED_NODEIDS.add(item.nodeid)
            except Exception:
                pass
            step_name = _get_last_step_name() or ""
            error_key_raw = step_name or type(call.excinfo.value).__name__
            error_key = _normalize_step_key(error_key_raw) if NORMALIZE_STEP_KEYS else error_key_raw
            # Узнаём состояние ДО отметки
            was_active_setup = False
            try:
                # Здесь важно использовать тот же домен, что и для алертов/агрегации (alert_domain),
                # иначе fixed в конце прогона может сработать ошибочно.
                was_active_setup = bool(_STATE.get("domain_errors", {}).get(alert_domain, {}).get(error_key, {}).get("active"))
            except Exception:
                was_active_setup = False
            err_raw = str(call.excinfo.value) if call.excinfo else ""
            err_url = _extract_url_from_error_text(err_raw)
            # Prefer URL from error text, else the most relevant test URL (param/page), else marker URL.
            incident_url = err_url or current_url or url_for_log
            alert_domain = _get_domain(incident_url) or (domain or "—")
            dom_key = (alert_domain, error_key)
            DOMAIN_ERROR_COUNTS[dom_key] += 1
            if incident_url:
                try:
                    DOMAIN_ERROR_URLS[dom_key].add(incident_url)
                except Exception:
                    pass
            new_count = _inc_url_counter(incident_url)
            try:
                # setup/teardown failure also counts as "test failed this run"
                pass
            except Exception:
                pass
            # Привязка тестов к паре (домен, шаг) и к URL для setup/teardown падений
            try:
                test_display_name = None
                try:
                    meta = TEST_META.get(item.nodeid) or {}
                    test_display_name = meta.get("title") or getattr(item, "name", None) or item.nodeid
                except Exception:
                    test_display_name = getattr(item, "name", None) or item.nodeid
                if test_display_name:
                    DOMAIN_ERROR_TESTS[dom_key].add(test_display_name)
                    try:
                        file_path = str(getattr(item, "fspath", "") or "")
                        if file_path:
                            DOMAIN_ERROR_FILES[dom_key].add(file_path)
                            TEST_NAME_FILES[test_display_name].add(file_path)
                    except Exception:
                        pass
                    if incident_url:
                        URL_ERROR_TESTS[incident_url].add(test_display_name)
            except Exception:
                pass
            # Log to Google Sheets once per nodeid on setup/teardown failure too, include repeat count
            try:
                if item.nodeid not in ERROR_LOGGED_NODEIDS:
                    test_name_for_log = None
                    try:
                        meta = TEST_META.get(item.nodeid) or {}
                        test_name_for_log = meta.get("title") or getattr(item, "name", None) or item.nodeid
                    except Exception:
                        test_name_for_log = getattr(item, "name", None) or item.nodeid
                    test_key_id = _test_id(item) or (test_name_for_log or item.nodeid)
                    test_disp = _test_display_name(item, form_title)
                    test_repeats = _inc_test_counter(alert_domain, test_key_id)
                    sheet_name = f"{(test_name_for_log or test_disp)} [{_short_id(test_key_id)}]"
                    _append_error_row(incident_url or url_for_log, sheet_name, _sanitize_error_text(str(call.excinfo.value)) if call.excinfo else "", test_repeats if incident_url else None)
                    ERROR_LOGGED_NODEIDS.add(item.nodeid)
            except Exception:
                pass
            # TG alert + mark active by TEST (setup/teardown)
            try:
                test_key_name = _test_id(item) or (form_title or getattr(item, "name", None) or item.nodeid)
                test_disp = _test_display_name(item, form_title)
            except Exception:
                test_key_name = _test_id(item) or (form_title or item.nodeid)
                test_disp = _test_display_name(item, form_title)
            try:
                _mark_test_failed_this_run(alert_domain, test_key_name)
                _append_executed_test_record(alert_domain, test_key_name, url=incident_url or url_for_log)
                _append_failed_test_record(
                    alert_domain,
                    test_key_name,
                    url=incident_url or url_for_log,
                    last_step=step_name or error_key_raw,
                    details=str(call.excinfo.value) if call.excinfo else None,
                )
            except Exception:
                pass
            try:
                # IMPORTANT: do not increment twice on setup/teardown
                test_repeats = int(_get_test_counter(alert_domain, test_key_name))
                if test_repeats <= 0:
                    test_repeats = int(_inc_test_counter(alert_domain, test_key_name))
            except Exception:
                test_repeats = 0
            if (not SUPPRESS_PERSISTENT_ALERTS) and _should_notify_persistent(int(test_repeats)):
                try:
                    if _claim_flag(alert_domain, f"test-{_safe_flag_key(alert_domain, test_key_name)}-{int(test_repeats)}", kind="persist_test"):
                        details = _sanitize_error_text(str(call.excinfo.value)) if call.excinfo else None
                        text = _format_persistent_test_message(
                            form_title=form_title,
                            url=incident_url or url_for_log,
                            test_name=test_disp,
                            details=details,
                            domain=alert_domain,
                            repeats_count=int(test_repeats),
                            last_step=step_name or error_key_raw,
                        )
                        _send_telegram_message(text)
                except Exception:
                    pass
            try:
                test_ent = _STATE.setdefault("test_errors", {}).setdefault(alert_domain, {}).setdefault(test_key_name, {})
                test_ent["active"] = True
                test_ent["last_failed_at"] = _utc_iso()
                test_ent["last_step"] = step_name or error_key_raw
                test_ent["display_name"] = test_disp
                if incident_url or url_for_log:
                    urls = test_ent.setdefault("urls", [])
                    if isinstance(urls, list):
                        u = incident_url or url_for_log
                        if u and u not in urls:
                            urls.append(u)
                        test_ent["urls"] = urls[-50:]
            except Exception:
                pass
    except Exception:
        pass

    if call.when == "call" and call.excinfo is not None:
        # Получаем фикстуру page если она есть
        page_fixture = None
        for fixture_name in item.funcargs:
            if 'page' in fixture_name:
                page_fixture = item.funcargs[fixture_name]
                break
        
        if page_fixture:
            try:
                # Получаем URL из параметров теста
                url = None
                for param_name, param_value in item.funcargs.items():
                    if 'url' in param_name and isinstance(param_value, str):
                        url = param_value
                        break
                
                if url:
                    success, status_code = check_page_status_code(page_fixture, url)
                    
                    # Добавляем информацию об ошибке в отчет
                    with allure.step("Анализ ошибки"):
                        allure.attach(
                            f"Тип ошибки: {type(call.excinfo.value).__name__}\n"
                            f"Сообщение: {str(call.excinfo.value)}\n"
                            f"URL: {url}\n"
                            f"Статус код: {status_code if status_code else 'Не определен'}",
                            name="Детали ошибки",
                            attachment_type=allure.attachment_type.TEXT
                        )
                        
                        if isinstance(call.excinfo.value, PlaywrightError):
                            allure.attach(
                                f"Playwright ошибка: {str(call.excinfo.value)}",
                                name="Playwright ошибка",
                                attachment_type=allure.attachment_type.TEXT
                            )
                            
            except Exception as e:
                with allure.step("Ошибка при анализе статус кода"):
                    allure.attach(
                        f"Не удалось проверить статус код: {str(e)}",
                        name="Ошибка анализа",
                        attachment_type=allure.attachment_type.TEXT
                    )

@pytest.fixture(scope="session")
def ttk_pack():
    """Базовый URL для тестов"""
    return "https://internet-mts-home.online/"



@pytest.fixture(scope="session")
def base_url():
    """Базовый URL для тестов"""
    return "https://mts-home.online/"


# Убрано: express_url как одиночный fixture. Теперь URL берутся только из файла EXPRESS_URLS_FILE.


def _read_urls_from_file(path: str) -> list[str]:
    """Считывает список URL из файла: по одному на строку, игнорируя пустые и начинающиеся с #."""
    urls: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = (raw or "").strip()
                if not line or line.startswith("#"):
                    continue
                urls.append(line)
    except Exception as e:
        raise Exception(f"Ошибка {e}")
    return urls


def _resolve_path_from_env(env_name: str) -> str | None:
    """Возвращает абсолютный путь из env (поддерживает относительные пути от корня репо)."""
    from pathlib import Path as _Path
    fp = os.getenv(env_name)
    if not fp:
        raise Exception("Файл не найден")
        return None
    fp = fp.strip().strip('"').strip("'")
    # Абсолютный путь — возвращаем как есть
    if os.path.isabs(fp):
        return fp
    # Относительный — резолвим относительно директории этого conftest.py (корень репо)
    root = str(_Path(__file__).resolve().parent)
    return str(_Path(root).joinpath(fp))




def pytest_generate_tests(metafunc):
    """Хук генерации тестов (сейчас не используется для express_url; параметризация вынесена в fixture)."""
    try:
        return
    except Exception:
        pass

@pytest.fixture(scope="session")
def second_url():
    """Базовый URL для тестов"""
    return "https://moskva.mts-home.online/"


@pytest.fixture(scope="session")
def third_url():
    """Базовый URL для тестов"""
    return "https://mts-home-gpon.ru/"


@pytest.fixture(scope="session")
def four_url():
    """Базовый URL для тестов"""
    return "https://mts-home-online.ru/"


@pytest.fixture(scope="session")
def five_url():
    """Базовый URL для тестов"""
    return "https://internet-mts-home.online/"


@pytest.fixture(scope="session")
def six_url():
    """Базовый URL для тестов"""
    return "https://mts-internet.online/"


@pytest.fixture(scope="session")
def seven_url():
    """Базовый URL для тестов"""
    return "http://mts-ru.ru/"


@pytest.fixture(scope="session")
def eight_url():
    """Базовый URL для тестов"""
    return "https://mega-premium.ru/"


@pytest.fixture(scope="session")
def eight_two_url():
    """Базовый URL для тестов"""
    return "https://mega-premium.ru/sankt-peterburg"


@pytest.fixture(scope="session")
def nine_url():
    """Базовый URL для тестов"""
    return "https://mega-home-internet.ru/"


@pytest.fixture(scope="session")
def mega_home_internet():
    """Базовый URL для тестов"""
    return "https://moskva.mega-home-internet.ru/"


@pytest.fixture(scope="session")
def nine_two_url():
    """Базовый URL для тестов"""
    return "https://sankt-peterburg.mega-home-internet.ru/"


@pytest.fixture(scope="session")
def providerdom_url():
    """Базовый URL для тестов"""
    return "https://providerdom.ru/"


@pytest.fixture(scope="session")
def msk_providerdom_url():
    """Базовый URL для тестов"""
    return "https://moskva.providerdom.ru/"


@pytest.fixture(scope="session")
def dom_provider_online_url():
    """Базовый URL для тестов"""
    return "https://dom-provider.online/"


@pytest.fixture(scope="session")
def beeline_online():
    """Базовый URL для тестов"""
    return "https://beeline-ru.online/"


@pytest.fixture(scope="session")
def ttk_internet():
    """Базовый URL для тестов"""
    return "https://ttk-internet.ru/"


@pytest.fixture(scope="session")
def ttk_online():
    """Базовый URL для тестов"""
    return "https://ttk-ru.online/"


@pytest.fixture(scope="session")
def online_beeline():
    """Базовый URL для тестов"""
    return "https://online-beeline.ru/"


@pytest.fixture(scope="session")
def msk_beeline_online():
    """Базовый URL для тестов"""
    return "https://moskva.beeline-ru.online/"


@pytest.fixture(scope="session")
def beeline_internet_online():
    """Базовый URL для тестов"""
    return "https://beeline-internet.online/"


@pytest.fixture(scope="session")
def beeline_pro():
    """Базовый URL для тестов"""
    return "https://beeline-ru.pro/"


@pytest.fixture(scope="session")
def beeline_home_online():
    """Базовый URL для тестов"""
    return "https://beeline-home.online/"


@pytest.fixture(scope="session")
def beeline_internet():
    """Базовый URL для тестов"""
    return "https://beelline-internet.ru/"


@pytest.fixture(scope="session")
def msk_beeline_online_dom():
    """Базовый URL для тестов"""
    return "https://moskva.beeline-ru.online/domashnij-internet"


@pytest.fixture(scope="session")
def msk_beeline_online_tv():
    """Базовый URL для тестов"""
    return "https://moskva.beeline-ru.online/domashnij-internet-tv"


@pytest.fixture(scope="session")
def msk_beeline_online_tariffs():
    """Базовый URL для тестов"""
    return "https://moskva.beeline-ru.online/tariffs-up"


@pytest.fixture(scope="session")
def msk_beeline_online_all_tariffs():
    """Базовый URL для тестов"""
    return "https://moskva.beeline-ru.online/all-tariffs"


@pytest.fixture(scope="session")
def tele_two():
    """Базовый URL для тестов"""
    return "https://t2-official.ru/"


@pytest.fixture(scope="session")
def msk_rtk_online():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/"


@pytest.fixture(scope="session")
def rtk_online_ru():
    """Базовый URL для тестов"""
    return "https://rtk-ru.online/"


@pytest.fixture(scope="session")
def rtk_internet_online_ru():
    """Базовый URL для тестов"""
    return "https://rt-internet.online/"


@pytest.fixture(scope="session")
def rtk_home_internet_ru():
    """Базовый URL для тестов"""
    return "https://rtk-home-internet.ru/"


@pytest.fixture(scope="session")
def rtk_moskva_online():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/"


@pytest.fixture(scope="session")
def rtk_balashiha_online():
    """Базовый URL для тестов"""
    return "https://balashiha.rtk-ru.online/"


@pytest.fixture(scope="session")
def rtk_domodedovo_online():
    """Базовый URL для тестов"""
    return "https://domodedovo.rtk-ru.online/"


@pytest.fixture(scope="session")
def rtk_internet_online_second():
    """Базовый URL для тестов"""
    return "https://rtk-internet.online/"


@pytest.fixture(scope="session")
def rtk_home_ru_second():
    """Базовый URL для тестов"""
    return "https://rtk-home.ru/"


@pytest.fixture(scope="session")
def msk_rtk_online_home_inter():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/domashnij-internet"


@pytest.fixture(scope="session")
def msk_rtk_online_home_inter_tv():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/internet-tv"


@pytest.fixture(scope="session")
def msk_rtk_online_home_inter_tv_mobile():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/internet-tv-mobile"


@pytest.fixture(scope="session")
def msk_rtk_online_home_tariffs():
    """Базовый URL для тестов"""
    return "https://moskva.rtk-ru.online/all-tariffs"


def _is_navigation_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "timeout",
        "timed out",
        "net::err_timed_out",
        "navigation timeout",
        "page.goto",
    )
    return any(marker in text for marker in markers)


def _attach_stable_goto(page, *, test_nodeid: str | None = None) -> None:
    """
    Lightweight retry wrapper around page.goto for transient navigation timeouts.
    Business checks remain unchanged; only flaky transport/load behavior is softened.
    """
    if not STABLE_GOTO_ENABLED:
        return

    original_goto = page.goto
    attempts = max(1, STABLE_GOTO_RETRIES + 1)
    seeded_origins: set[str] = set()
    prod_cookie_hosts = (
        "rt-internet.online",
        "rtk-home-internet.ru",
        "rtk-home.ru",
        "rtk-ru.online",
        "moskva.rtk-ru.online",
    )

    def _cookie_origin(target_url: str) -> str | None:
        try:
            parsed = urlparse(str(target_url))
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return None
        return None

    def _is_prod_landing_origin(origin: str | None) -> bool:
        if not origin:
            return False
        try:
            host = (urlparse(origin).netloc or "").lower()
        except Exception:
            host = ""
        return any(host == suffix or host.endswith("." + suffix) for suffix in prod_cookie_hosts)

    def _infer_case_variant(nodeid: str | None) -> str | None:
        if not nodeid:
            return None
        if "__A__" in nodeid:
            return "A"
        if "__B__" in nodeid:
            return "B"
        return None

    def _normalize_cookie_value(raw_value: object) -> str | None:
        if raw_value is None:
            return None
        value = str(raw_value).strip().strip('"').strip("'")
        if not value:
            return None
        if value.lower() in {"disabled", "disable", "none", "off", "false", "0"}:
            return None
        return value

    def _parse_cookie_overrides(target_url: str | None = None) -> list[dict]:
        overrides: dict[str, str] = {}

        raw_map = _normalize_cookie_value(os.getenv("COOKIE_OVERRIDES"))
        if raw_map:
            try:
                parsed = json.loads(raw_map)
                if isinstance(parsed, dict):
                    for name, value in parsed.items():
                        cookie_name = str(name).strip()
                        cookie_value = _normalize_cookie_value(value)
                        if cookie_name and cookie_value is not None:
                            overrides[cookie_name] = cookie_value
                else:
                    raise ValueError("COOKIE_OVERRIDES must be a JSON object")
            except Exception:
                for chunk in re.split(r"[;\n,]+", raw_map):
                    item = chunk.strip()
                    if not item or "=" not in item:
                        continue
                    cookie_name, cookie_value = item.split("=", 1)
                    cookie_name = cookie_name.strip()
                    cookie_value = _normalize_cookie_value(cookie_value)
                    if cookie_name and cookie_value is not None:
                        overrides[cookie_name] = cookie_value

        env_cookie_map = (
            ("TESTNEWADDRESSPOISK_COOKIE_VALUE", "testNewAddressPoisk"),
            ("TESTNEWADDRESSPOISK_COOKIE", "testNewAddressPoisk"),
            ("AB_WP_THEME_VARIANT_COOKIE_VALUE", "AB_wp_theme_variant"),
            ("AB_WP_THEME_VARIANT_COOKIE", "AB_wp_theme_variant"),
            ("THEME_AB_VARIANT_COOKIE_VALUE", "theme_ab_variant"),
            ("THEME_AB_VARIANT_COOKIE", "theme_ab_variant"),
        )
        for env_name, cookie_name in env_cookie_map:
            cookie_value = _normalize_cookie_value(os.getenv(env_name))
            if cookie_value is not None and cookie_name not in overrides:
                overrides[cookie_name] = cookie_value

        inferred_variant = _infer_case_variant(test_nodeid)
        if inferred_variant and _is_prod_landing_origin(target_url):
            overrides.setdefault("testNewAddressPoisk", inferred_variant)

        cookie_payload = []
        for cookie_name, cookie_value in overrides.items():
            cookie_payload.append(
                {
                    "name": cookie_name,
                    "value": cookie_value,
                    "url": None,
                }
            )
        return cookie_payload

    def _seed_manual_cookies(target_url: str) -> None:
        if not target_url:
            return
        origin = _cookie_origin(target_url)
        if not origin or origin in seeded_origins:
            return
        cookie_payload = _parse_cookie_overrides(origin)
        if not cookie_payload:
            return
        for cookie in cookie_payload:
            cookie["url"] = origin
        try:
            page.context.add_cookies(cookie_payload)
            seeded_origins.add(origin)
        except Exception:
            pass

    def _stable_goto(url, *args, **kwargs):
        _seed_manual_cookies(url)
        for attempt in range(attempts):
            call_kwargs = dict(kwargs)
            if attempt > 0:
                # Retry in lighter mode when initial full-load navigation timed out.
                call_kwargs.setdefault("wait_until", "domcontentloaded")
                call_kwargs.setdefault("timeout", PAGE_NAVIGATION_TIMEOUT_MS)
            try:
                return original_goto(url, *args, **call_kwargs)
            except PlaywrightError as exc:
                if not _is_navigation_timeout_error(exc) or attempt == attempts - 1:
                    raise
                try:
                    time.sleep(STABLE_GOTO_RETRY_SLEEP_SEC)
                except Exception:
                    pass

    try:
        page.goto = _stable_goto
    except Exception:
        # If Playwright object forbids attribute override, keep default behavior.
        pass


@pytest.fixture(scope="function")
def browser_fixture():
    """
    Фикстура для создания и управления браузером.
    Режим headless контролируется через .env файл
    """
    # Получаем значение HEADLESS из .env (по умолчанию True если не указано)
    headless = _env_bool("HEADLESS", True)

    with sync_playwright() as playwright:
        # Запускаем браузер с нужными настройками
        browser = playwright.chromium.launch(headless=headless)
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def browser_fixture_ignore_https():
    """
    Фикстура для создания браузера с игнорированием ошибок HTTPS
    """
    headless = _env_bool("HEADLESS", True)

    with sync_playwright() as playwright:
        # Запускаем браузер с отключенной проверкой сертификатов
        browser = playwright.chromium.launch(
            headless=headless,
            ignore_https_errors=True
        )
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def page_fixture(browser_fixture, request):
    """
    Фикстура для создания новой страницы в браузере
    """
    # Создаем контекст и страницу
    context = browser_fixture.new_context()
    page = context.new_page()
    try:
        page.set_default_navigation_timeout(PAGE_NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass
    try:
        page.set_default_timeout(PAGE_ACTION_TIMEOUT_MS)
    except Exception:
        pass
    _attach_stable_goto(page, test_nodeid=getattr(request.node, "nodeid", None))
    yield page
    # Закрываем контекст после использования
    context.close()


@pytest.fixture(scope="function")
def page_fixture_ignore_https(browser_fixture_ignore_https, request):
    """
    Фикстура для создания страницы с игнорированием ошибок HTTPS
    """
    context = browser_fixture_ignore_https.new_context(ignore_https_errors=True)
    page = context.new_page()
    try:
        page.set_default_navigation_timeout(PAGE_NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass
    try:
        page.set_default_timeout(PAGE_ACTION_TIMEOUT_MS)
    except Exception:
        pass
    _attach_stable_goto(page, test_nodeid=getattr(request.node, "nodeid", None))
    yield page
    context.close()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    # Aggregated alerts, fixed notifications, run summary, and persistence
    try:
        if not ALERTS_ENABLED:
            return

        # xdist: only master should send fixed/summary and persist shared state,
        # workers already sent failure alerts and wrote run-scoped records.
        try:
            if getattr(session.config, "workerinput", None) is not None:
                return
        except Exception:
            pass

        # Массовая логика удалена

        # FIXED по тесту в конце прогона (межпрогонный):
        # шлём только если после последнего fixed был новый failed и в этом прогоне этот тест уже НЕ падал.
        try:
            # First, merge "failed tests this run" from worker jsonl logs into persistent state.
            failed_this_run: set[tuple[str, str]] = set()
            executed_this_run: set[tuple[str, str]] = set()
            try:
                for fp in sorted(_FAILED_TESTS_DIR.glob("*.jsonl")):
                    try:
                        with fp.open("r", encoding="utf-8") as f:
                            for line in f:
                                line = (line or "").strip()
                                if not line:
                                    continue
                                try:
                                    rec = json.loads(line)
                                except Exception:
                                    continue
                                d = str(rec.get("domain") or "").strip() or "—"
                                t = str(rec.get("test") or "").strip()
                                if not t:
                                    continue
                                failed_this_run.add((d, t))
                                try:
                                    ent = _STATE.setdefault("test_errors", {}).setdefault(d, {}).setdefault(t, {})
                                    ent["active"] = True
                                    ent["last_failed_at"] = _utc_iso()
                                    step = str(rec.get("step") or "").strip()
                                    if step:
                                        ent["last_step"] = step
                                    u = str(rec.get("url") or "").strip()
                                    if u:
                                        urls = ent.setdefault("urls", [])
                                        if isinstance(urls, list):
                                            if u not in urls:
                                                urls.append(u)
                                            ent["urls"] = urls[-50:]
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception:
                failed_this_run = set()

            # Also load "executed tests this run" (so we don't "fix" tests that weren't run)
            try:
                for fp in sorted(_EXECUTED_TESTS_DIR.glob("*.jsonl")):
                    try:
                        with fp.open("r", encoding="utf-8") as f:
                            for line in f:
                                line = (line or "").strip()
                                if not line:
                                    continue
                                try:
                                    rec = json.loads(line)
                                except Exception:
                                    continue
                                d = str(rec.get("domain") or "").strip() or "—"
                                t = str(rec.get("test") or "").strip()
                                if not t:
                                    continue
                                executed_this_run.add((d, t))
                    except Exception:
                        continue
            except Exception:
                executed_this_run = set()

            for domain, tmap in list((_STATE.get("test_errors", {}) or {}).items()):
                for test_name, entry in list((tmap or {}).items()):
                    try:
                        if not bool((entry or {}).get("active")):
                            continue
                        # Fixed is meaningful only if the test actually ran in this run.
                        if (domain, test_name) not in executed_this_run:
                            continue
                        # Prefer master-aggregated failures; fallback to flag check
                        if (domain, test_name) in failed_this_run or _test_failed_this_run(domain, test_name):
                            continue
                        last_failed_at = str((entry or {}).get("last_failed_at") or "")
                        last_fixed_at = str((entry or {}).get("last_fixed_at") or "")
                        if not last_failed_at:
                            continue
                        if last_fixed_at and last_failed_at <= last_fixed_at:
                            continue
                        if not _claim_flag(domain, f"fixed-test-{_safe_flag_key(domain, test_name)}-end", kind="fixed_test"):
                            continue
                        sample_url = None
                        try:
                            urls = (entry or {}).get("urls") or []
                            if isinstance(urls, list) and urls:
                                sample_url = str(urls[-1])
                        except Exception:
                            sample_url = None
                        last_step = None
                        try:
                            last_step = str((entry or {}).get("last_step") or "") or None
                        except Exception:
                            last_step = None
                        display = None
                        try:
                            display = str((entry or {}).get("display_name") or "").strip() or None
                        except Exception:
                            display = None
                        msg = _format_fixed_test_message(
                            domain=domain,
                            test_name=(display or test_name),
                            sample_url=sample_url,
                            form_title=(display or test_name),
                            last_step=last_step,
                        )
                        _send_telegram_message(msg)
                        # деактивировать и сбросить счётчик по тесту
                        try:
                            _STATE.setdefault("test_errors", {}).setdefault(domain, {}).setdefault(test_name, {})["active"] = False
                            _STATE.setdefault("test_errors", {}).setdefault(domain, {}).setdefault(test_name, {})["last_fixed_at"] = _utc_iso()
                        except Exception:
                            pass
                        try:
                            _reset_test_counter(domain, test_name)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            pass

        # Конечные fixed-оповещения по невстреченным в этом прогоне случаям отключены — только мгновенные при прохождении

        # Run summary (optional)
        if RUN_SUMMARY_ENABLED:
            summary_parts = []
            try:
                if RUN_SUMMARY_LONG_ENABLED:
                    summary_parts.append(_format_run_summary())
            except Exception:
                pass
            try:
                if RUN_SUMMARY_SHORT_ENABLED:
                    summary_parts.append(_format_short_run_summary())
            except Exception:
                pass
            if summary_parts:
                # Send as a single message to avoid duplicate "success" notifications.
                _send_telegram_message("\n\n".join([p for p in summary_parts if p]))
    finally:
        _save_state()
        # Append per-run summary line for daily aggregation
        try:
            record = {
                "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pages": RUN_TOTAL_PAGES,
                "passed": RUN_PASSED,
                "failed": RUN_FAILED,
                "landings": sorted(list(RUN_LANDINGS)),
            }
            try:
                _RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            with _RUN_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # do not break the session finish on logging errors
            pass
        return


