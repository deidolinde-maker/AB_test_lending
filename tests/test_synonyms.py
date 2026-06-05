import pytest

from tests._search_flow import run_search_case

pytestmark = [pytest.mark.e2e, pytest.mark.synonyms]


def test_synonym_search(synonym_case, page, context, tmp_path, site_config_map, form_config_map):
    run_search_case(
        case=synonym_case,
        page=page,
        context=context,
        site_config=site_config_map[synonym_case.site],
        form_config=form_config_map[synonym_case.form],
        tmp_path=tmp_path,
        verify_search_payload=(synonym_case.variant == "B"),
    )
