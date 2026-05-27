import pytest

from tests._search_flow import run_regional_navigation_case

pytestmark = [pytest.mark.e2e, pytest.mark.regional_navigation]


def test_regional_navigation_chain(
    navigation_case,
    page,
    context,
    tmp_path,
    loaded_config,
    site_config_map,
    form_config_map,
):
    run_regional_navigation_case(
        navigation_case=navigation_case,
        page=page,
        context=context,
        site_config=site_config_map[navigation_case.site],
        form_config=form_config_map["profit"],
        addresses_raw=loaded_config.addresses,
        tmp_path=tmp_path,
    )
