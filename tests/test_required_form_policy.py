from tests._search_flow import _is_form_required_for_url


def test_required_forms_policy_for_all_sites(loaded_config, site_config_map, form_config_map):
    required_expected = {"profit", "connection", "checkaddress"}
    optional_expected = {"undecided", "moving", "express_connection"}

    for site in loaded_config.sites:
        required_by_url = site.required_forms_by_url_type

        assert set(required_by_url.keys()) == set(site.urls)
        for url_type in site.urls:
            for form_name in required_expected:
                assert _is_form_required_for_url(site, form_config_map[form_name], url_type)
            for form_name in optional_expected:
                assert not _is_form_required_for_url(site, form_config_map[form_name], url_type)
