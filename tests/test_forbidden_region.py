import pytest

from tests._search_flow import run_negative_search_case

pytestmark = [pytest.mark.e2e, pytest.mark.forbidden_region]


def test_forbidden_region_address_not_found(case, page, context, tmp_path, site_config_map, form_config_map):
    run_negative_search_case(
        case=case,
        page=page,
        context=context,
        site_config=site_config_map[case.site],
        form_config=form_config_map[case.form],
        tmp_path=tmp_path,
    )
