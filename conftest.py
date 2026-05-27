from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from helpers.allure_attachments import attach_video_file
from helpers.config_loader import load_config
from helpers.test_case_factory import (
    ab_cookie_cases,
    adjacent_cases,
    forbidden_region_cases,
    isolation_cases,
    main_search_cases,
    region_change_cases,
    regional_navigation_cases,
    synonym_cases,
)


@lru_cache(maxsize=1)
def _loaded():
    return load_config(Path(__file__).parent / "config")


def pytest_addoption(parser):
    parser.addoption("--site", action="store", default="all")
    parser.addoption("--url-type", action="store", default="all")
    parser.addoption("--variant", action="store", default="all", choices=["all", "A", "B"])
    parser.addoption(
        "--dataset",
        action="store",
        default="all",
        choices=["all", "main_search", "isolation", "adjacent", "forbidden_region", "synonyms"],
    )
    parser.addoption("--form", action="store", default="all")
    parser.addoption("--case-id", action="store", default="all")
    parser.addoption("--run-e2e", action="store_true", default=False)
    parser.addoption(
        "--video-mode",
        action="store",
        default="on_failure",
        choices=["off", "on_failure", "always"],
    )


def _matches_filter(value: str | None, selected: str) -> bool:
    if selected in {"all", "", None}:
        return True
    if value is None:
        return False
    return value == selected


def _case_passes_cli(case, config) -> bool:
    return (
        _matches_filter(getattr(case, "site", None), config.getoption("--site"))
        and _matches_filter(getattr(case, "url_type", None), config.getoption("--url-type"))
        and _matches_filter(getattr(case, "variant", None), config.getoption("--variant"))
        and _matches_filter(getattr(case, "dataset", None), config.getoption("--dataset"))
        and _matches_filter(getattr(case, "form", None), config.getoption("--form"))
        and _matches_filter(getattr(case, "case_id", None), config.getoption("--case-id"))
    )


def _case_ids(cases):
    return [case.pytest_id for case in cases]


def pytest_generate_tests(metafunc):
    data = _loaded()
    cfg = metafunc.config
    fn = metafunc.function.__name__

    if "site_url_case" in metafunc.fixturenames:
        cases = [case for case in ab_cookie_cases(data) if _case_passes_cli(case, cfg)]
        metafunc.parametrize("site_url_case", cases, ids=_case_ids(cases))
        return

    if "navigation_case" in metafunc.fixturenames:
        variant_opt = cfg.getoption("--variant")
        cases = regional_navigation_cases(data, None if variant_opt == "all" else variant_opt)
        cases = [case for case in cases if _case_passes_cli(case, cfg)]
        metafunc.parametrize("navigation_case", cases, ids=_case_ids(cases))
        return

    if "synonym_case" in metafunc.fixturenames:
        cases = [case for case in synonym_cases(data) if _case_passes_cli(case, cfg)]
        metafunc.parametrize("synonym_case", cases, ids=_case_ids(cases))
        return

    if "case" not in metafunc.fixturenames:
        return

    if fn == "test_search_variant_a":
        cases = main_search_cases(data, "A")
    elif fn == "test_search_variant_b":
        cases = main_search_cases(data, "B")
    elif fn == "test_variant_a_does_not_find_v2_address":
        cases = isolation_cases(data, "A")
    elif fn == "test_variant_b_does_not_find_v1_address":
        cases = isolation_cases(data, "B")
    elif fn == "test_adjacent_search":
        cases = adjacent_cases(data)
    elif fn == "test_forbidden_region_address_not_found":
        cases = forbidden_region_cases(data)
    elif fn == "test_region_change_inside_form_does_not_change_url":
        cases = region_change_cases(data)
    else:
        cases = []

    cases = [case for case in cases if _case_passes_cli(case, cfg)]
    metafunc.parametrize("case", cases, ids=_case_ids(cases))


def pytest_collection_modifyitems(config, items):
    deselected = [item for item in items if "[NOTSET" in item.name]
    if deselected:
        for item in deselected:
            items.remove(item)
        config.hook.pytest_deselected(items=deselected)

    selected_dataset = config.getoption("--dataset")
    if selected_dataset not in {"all", "", None}:
        dataset_marker_map = {
            "main_search": {"variant_a", "variant_b"},
            "isolation": {"isolation"},
            "adjacent": {"adjacent"},
            "forbidden_region": {"forbidden_region"},
            "synonyms": {"synonyms"},
        }
        allowed_markers = dataset_marker_map[selected_dataset]
        to_drop = [
            item
            for item in items
            if not any(marker in item.keywords for marker in allowed_markers)
        ]
        if to_drop:
            for item in to_drop:
                items.remove(item)
            config.hook.pytest_deselected(items=to_drop)

    if config.getoption("--run-e2e"):
        return
    skip_marker = pytest.mark.skip(reason="Use --run-e2e to run browser scenarios")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def browser_context_args(browser_context_args, request, tmp_path):
    # Record videos only for explicit e2e runs.
    if not request.config.getoption("--run-e2e"):
        return browser_context_args
    if request.config.getoption("--video-mode") == "off":
        return browser_context_args
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    setattr(request.node, "_video_dir", str(video_dir))
    args = dict(browser_context_args)
    args["record_video_dir"] = str(video_dir)
    args.setdefault("record_video_size", {"width": 1366, "height": 900})
    return args


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when in {"setup", "call"} and report.failed:
        setattr(item, "_test_failed", True)
    if report.when != "teardown":
        return
    video_dir = getattr(item, "_video_dir", None)
    if not video_dir:
        return
    video_mode = item.config.getoption("--video-mode")
    path = Path(video_dir)
    if not path.exists():
        return
    keep_video = video_mode == "always" or (
        video_mode == "on_failure" and getattr(item, "_test_failed", False)
    )
    if not keep_video:
        for video_path in path.glob("*.webm"):
            try:
                video_path.unlink(missing_ok=True)
            except Exception:
                pass
        return
    for idx, video_path in enumerate(sorted(path.glob("*.webm")), start=1):
        attach_video_file(video_path, name=f"video_{idx}")


@pytest.fixture(scope="session")
def loaded_config():
    return _loaded()


@pytest.fixture(scope="session")
def site_config_map(loaded_config):
    return {site.name: site for site in loaded_config.sites}


@pytest.fixture(scope="session")
def form_config_map(loaded_config):
    return {form.name: form for form in loaded_config.forms}
