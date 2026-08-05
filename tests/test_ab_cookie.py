import pytest

from helpers.ab_cookie import (
    assert_ab_cookie_absent,
    assert_ab_cookie_not_changed,
    get_ym_uid_cookie,
    set_theme_ab_cookie,
    set_wp_theme_ab_cookie,
    wait_ab_cookie,
)
from helpers.allure_attachments import attach_json
from pages.landing_page import LandingPage

pytestmark = [pytest.mark.e2e, pytest.mark.ab_cookie]


def test_ab_cookie_assigned_on_clean_context(site_url_case, page, context, site_config_map):
    site_config = site_config_map[site_url_case.site]
    landing = LandingPage(page, site_config)
    target_url = site_config.urls[site_url_case.url_type]

    assert_ab_cookie_absent(context)
    if site_url_case.site == "stage_project":
        set_wp_theme_ab_cookie(context, target_url, "A")
    set_theme_ab_cookie(context, target_url, "a")
    landing.open(site_url_case.url_type)
    variant = wait_ab_cookie(context)
    assert variant in {"A", "B"}

    attach_json(
        "ab_cookie_assignment",
        {
            "site": site_url_case.site,
            "url_type": site_url_case.url_type,
            "variant": variant,
            "ym_uid": get_ym_uid_cookie(context),
        },
    )


def test_ab_cookie_persists_after_reload(site_url_case, page, context, site_config_map):
    site_config = site_config_map[site_url_case.site]
    landing = LandingPage(page, site_config)
    target_url = site_config.urls[site_url_case.url_type]

    if site_url_case.site == "stage_project":
        set_wp_theme_ab_cookie(context, target_url, "A")
    set_theme_ab_cookie(context, target_url, "a")
    landing.open(site_url_case.url_type)
    initial_variant = wait_ab_cookie(context)
    page.reload(wait_until="domcontentloaded")
    assert_ab_cookie_not_changed(context, initial_variant)

    attach_json(
        "ab_cookie_persistence",
        {
            "site": site_url_case.site,
            "url_type": site_url_case.url_type,
            "initial_variant": initial_variant,
            "after_reload_variant": wait_ab_cookie(context),
        },
    )
