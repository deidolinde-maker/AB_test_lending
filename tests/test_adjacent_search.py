import pytest

from tests._search_flow import run_search_case

pytestmark = [pytest.mark.e2e, pytest.mark.adjacent]


def test_adjacent_search(case, page, context, tmp_path, site_config_map, form_config_map):
    run_search_case(
        case=case,
        page=page,
        context=context,
        site_config=site_config_map[case.site],
        form_config=form_config_map[case.form],
        tmp_path=tmp_path,
        verify_search_payload=(case.variant == "B"),
    )
