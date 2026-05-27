import pytest

from tests._search_flow import run_negative_search_case

pytestmark = [pytest.mark.e2e, pytest.mark.isolation]


def test_variant_a_does_not_find_v2_address(case, page, context, tmp_path, site_config_map, form_config_map):
    run_negative_search_case(
        case=case,
        page=page,
        context=context,
        site_config=site_config_map[case.site],
        form_config=form_config_map[case.form],
        tmp_path=tmp_path,
    )


def test_variant_b_does_not_find_v1_address(case, page, context, tmp_path, site_config_map, form_config_map):
    run_negative_search_case(
        case=case,
        page=page,
        context=context,
        site_config=site_config_map[case.site],
        form_config=form_config_map[case.form],
        tmp_path=tmp_path,
    )
