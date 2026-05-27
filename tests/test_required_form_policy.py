from tests._search_flow import _is_form_required_for_url


def test_required_forms_policy_for_mts_site(loaded_config, site_config_map, form_config_map):
    site = site_config_map["mts_internet_online"]
    required_by_url = site.required_forms_by_url_type

    # Policy is explicitly defined per url_type for this landing.
    assert set(required_by_url.keys()) == {
        "domain_without_region",
        "moscow_subdomain",
        "balashikha_folder",
        "domodedovo_folder",
    }

    required_expected = {"profit", "connection", "checkaddress"}
    optional_expected = {"undecided", "moving", "express_connection"}

    for url_type in site.urls:
        for form_name in required_expected:
            assert _is_form_required_for_url(site, form_config_map[form_name], url_type)
        for form_name in optional_expected:
            assert not _is_form_required_for_url(site, form_config_map[form_name], url_type)
