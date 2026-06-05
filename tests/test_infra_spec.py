from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

import pytest

from helpers.config_loader import load_config
from helpers.test_case_factory import main_search_cases, synonym_cases


PYTEST_ID_PATTERN = re.compile(
    r"^[a-z0-9_]+__[a-z0-9_]+__[a-z_]+__[AB]__[A-Za-z0-9_]+(?:__.+)?$"
)


def test_yaml_validation_fails_fast_on_missing_required_key():
    src = Path(__file__).resolve().parents[1] / "config"
    dst = Path.cwd() / f"_tmp_config_copy_{uuid.uuid4().hex}"
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)

    sites_path = dst / "sites.yaml"
    original = sites_path.read_text(encoding="utf-8")
    sites_path.write_text(original.replace("sites:", "sites_broken:", 1), encoding="utf-8")

    try:
        with pytest.raises(ValueError, match="sites.yaml is missing required keys: sites"):
            load_config(dst)
    finally:
        shutil.rmtree(dst, ignore_errors=True)


def test_main_search_case_ids_are_unique_and_stable_format(loaded_config):
    for variant in ("A", "B"):
        cases = main_search_cases(loaded_config, variant)
        ids = [case.pytest_id for case in cases]
        assert len(ids) == len(set(ids))
        assert all(PYTEST_ID_PATTERN.match(case_id) for case_id in ids)


def test_business_form_is_not_generated_in_iteration_one(loaded_config):
    cases = main_search_cases(loaded_config, "A") + main_search_cases(loaded_config, "B")
    assert all(case.form != "business" for case in cases)


def test_synonym_dataset_has_cases_for_real_addresses(loaded_config):
    cases = synonym_cases(loaded_config)
    assert cases, "synonym_cases should not be empty for current config"


def test_b_search_cases_define_locality_context(loaded_config):
    cases = main_search_cases(loaded_config, "B")
    lipovy = next(case for case in cases if case.case_id == "B_moscow_lipovy_park")
    domodedovo = next(case for case in cases if case.case_id == "B_mo_domodedovo_kolomiytsa")
    assert lipovy.expected_locality_id == 16
    assert lipovy.expected_locality_name == "п Коммунарка"
    assert domodedovo.expected_locality_id == 26
    assert domodedovo.expected_locality_name == "мкр Центральный"
