from __future__ import annotations
from pathlib import Path

import pytest

from components.address_form import AddressForm
from helpers.ab_cookie import (
    assert_ab_cookie_value,
    assert_ab_cookie_not_changed,
    get_ab_cookie,
    get_ym_uid_cookie,
    set_ab_cookie,
    wait_ab_cookie,
)
from helpers.allure_attachments import attach_json, attach_png_file, attach_text
from helpers.console_recorder import ConsoleRecorder
from helpers.network_recorder import NetworkRecorder
from pages.landing_page import LandingPage


def _is_form_required_for_url(site_config, form_config, url_type: str) -> bool:
    required_by_url = getattr(site_config, "required_forms_by_url_type", {}) or {}
    if url_type in required_by_url:
        required_forms = required_by_url.get(url_type) or []
        return form_config.name in required_forms
    return not form_config.optional


def run_search_case(
    *,
    case,
    page,
    context,
    site_config,
    form_config,
    tmp_path: Path,
    verify_v2_endpoints: bool = False,
) -> None:
    recorder = NetworkRecorder(page, case_id=case.case_id, variant=case.variant)
    console = ConsoleRecorder(page)
    landing = LandingPage(page, site_config)
    form = AddressForm(page, form_config)
    target_url = site_config.urls[case.url_type]

    attach_json(
        "case_context",
        {
            "case_id": case.case_id,
            "site": case.site,
            "url_type": case.url_type,
            "form": case.form,
            "variant": case.variant,
            "dataset": case.dataset,
            "region": case.region,
            "expected_street": case.expected_street,
            "expected_house": case.expected_house,
            "expected_id": case.expected_id,
            "expected_id_type": case.expected_id_type,
        },
    )

    try:
        set_ab_cookie(context, target_url, case.variant)
        recorder.start()
        console.start()

        landing.open(case.url_type)
        assert_ab_cookie_value(context, case.variant)

        form.open()
        if not form.is_present():
            is_required = _is_form_required_for_url(site_config, form_config, case.url_type)
            if not is_required:
                pytest.skip(
                    f"Optional form '{form_config.name}' is not present for case {case.pytest_id}"
                )
            pytest.fail(f"Required form '{form_config.name}' is not present for case {case.pytest_id}")

        initial_url = landing.get_current_url()
        expected_region_for_url = site_config.expected_regions.get(case.url_type)
        should_change_region = expected_region_for_url != case.region
        if should_change_region and form.can_change_city():
            form.change_city_inside_form(case.region)
            current_url = landing.get_current_url()
            assert current_url == initial_url, (
                f"Step: Change region inside form\nExpected URL: {initial_url}\nActual URL: {current_url}"
            )

        form.fill_street(case.street_query)
        form.wait_street_suggest()
        form.assert_street_in_suggest(case.expected_street)
        form.select_street(case.expected_street, preferred_region=case.region)

        form.fill_house(case.house_query)
        form.wait_house_suggest()
        form.assert_house_in_suggest(case.expected_house)
        form.select_house(case.expected_house)

        actual_id = form.get_selected_house_id()
        assert str(actual_id) == str(case.expected_id), (
            f"Step: Validate selected address ID\nExpected: {case.expected_id}\nActual: {actual_id}"
        )

        if verify_v2_endpoints:
            recorder.assert_v2_endpoints_for_b()
    except Exception:
        screenshot_path = tmp_path / f"{case.case_id}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        attach_png_file(screenshot_path, "failure_screenshot")
        try:
            form_dom = form.get_form_dom_snapshot()
            if form_dom:
                attach_text("form_dom_snapshot", form_dom)
        except Exception:
            pass
        try:
            debug_state = form.collect_debug_state()
            if debug_state:
                attach_json("form_debug_state", debug_state)
        except Exception:
            pass
        raise
    finally:
        console.stop()
        recorder.stop()
        attach_json("cookies", context.cookies())
        attach_json("network_events", [event.__dict__ for event in recorder.events])
        if case.variant == "B":
            attach_json("network_b_endpoint_summary", recorder.build_b_endpoint_summary())
        attach_json("console_errors", console.errors)
        attach_json(
            "ab_tracking",
            {
                "ab_cookie": get_ab_cookie(context),
                "ym_uid": get_ym_uid_cookie(context),
            },
        )
        storage_path = tmp_path / f"{case.case_id}_storage_state.json"
        context.storage_state(path=str(storage_path))
        attach_text("storage_state_path", str(storage_path))


def run_regional_navigation_case(
    *,
    navigation_case,
    page,
    context,
    site_config,
    form_config,
    addresses_raw: list[dict],
    tmp_path: Path,
) -> None:
    target_url = site_config.urls[navigation_case.start_url_type]
    set_ab_cookie(context, target_url, navigation_case.variant)

    chain = site_config.regional_navigation_chain
    url_type_by_url = {url.rstrip("/"): url_type for url_type, url in site_config.urls.items()}
    by_region: dict[str, dict] = {}
    for raw in addresses_raw:
        if raw["variant"] != navigation_case.variant:
            continue
        by_region[raw["region"]] = raw

    landing = LandingPage(page, site_config)
    form = AddressForm(page, form_config)

    landing.open(navigation_case.start_url_type)
    initial_variant = wait_ab_cookie(context)
    assert initial_variant == navigation_case.variant, (
        f"Step: Start regional navigation\nExpected variant: {navigation_case.variant}\nActual: {initial_variant}"
    )

    for idx, step in enumerate(chain):
        expected_url = step.get("expected_url")
        expected_region = step.get("expected_region")
        step_name = step.get("step", f"step_{idx}")
        step_url_type = step.get("url_type")
        if not step_url_type and expected_url:
            step_url_type = url_type_by_url.get(expected_url.rstrip("/"))
        if not step_url_type:
            step_url_type = navigation_case.start_url_type

        if idx > 0 and expected_url:
            try:
                landing.select_region_from_page_navigation(expected_region or "")
            except Exception:
                page.goto(expected_url, wait_until="domcontentloaded")

        if expected_url:
            landing.assert_url_is_expected(expected_url)

        if expected_region:
            body_text = page.locator("body").inner_text().lower()
            assert expected_region.lower() in body_text, (
                f"Step: {step_name} region check\nExpected region text: {expected_region}\nActual page did not contain it"
            )

        # Skip search on initial no-region step.
        if idx == 0:
            assert_ab_cookie_not_changed(context, navigation_case.variant)
            continue

        # Find address fixture for this region or region alias.
        address_case = by_region.get(expected_region or "")
        if address_case is None and (expected_region or "").lower() == "домодедово":
            address_case = by_region.get("Домодедово")
        if address_case is None and (expected_region or "").lower() == "москва":
            address_case = by_region.get("Москва")
        if address_case is None and (expected_region or "").lower() == "балашиха":
            address_case = by_region.get("Балашиха")
        if address_case is None:
            # If we don't have exact mapped data for step region, continue with chain validation.
            assert_ab_cookie_not_changed(context, navigation_case.variant)
            continue

        form.open()
        if not form.is_present():
            is_required = _is_form_required_for_url(site_config, form_config, step_url_type)
            if not is_required:
                continue
            pytest.fail(f"Required form '{form_config.name}' is not present on regional step {step_name}")

        form.fill_street(address_case["street_query"])
        form.wait_street_suggest()
        form.assert_street_in_suggest(address_case["expected_street"])
        form.select_street(address_case["expected_street"], preferred_region=address_case["region"])

        form.fill_house(address_case["house_query"])
        form.wait_house_suggest()
        form.assert_house_in_suggest(address_case["expected_house"])
        form.select_house(address_case["expected_house"])

        actual_id = form.get_selected_house_id()
        assert str(actual_id) == str(address_case["expected_id"]), (
            f"Step: {step_name} id check\nExpected ID: {address_case['expected_id']}\nActual ID: {actual_id}"
        )
        assert_ab_cookie_not_changed(context, navigation_case.variant)

    attach_json(
        "regional_navigation_summary",
        {
            "site": navigation_case.site,
            "variant": navigation_case.variant,
            "steps": [step.get("step") for step in chain],
        },
    )


def run_negative_search_case(
    *,
    case,
    page,
    context,
    site_config,
    form_config,
    tmp_path: Path,
) -> None:
    recorder = NetworkRecorder(page, case_id=case.case_id, variant=case.variant)
    console = ConsoleRecorder(page)
    landing = LandingPage(page, site_config)
    form = AddressForm(page, form_config)
    target_url = site_config.urls[case.url_type]

    try:
        set_ab_cookie(context, target_url, case.variant)
        recorder.start()
        console.start()

        landing.open(case.url_type)
        assert_ab_cookie_value(context, case.variant)

        form.open()
        if not form.is_present():
            is_required = _is_form_required_for_url(site_config, form_config, case.url_type)
            if not is_required:
                pytest.skip(
                    f"Optional form '{form_config.name}' is not present for case {case.pytest_id}"
                )
            pytest.fail(f"Required form '{form_config.name}' is not present for case {case.pytest_id}")

        form.fill_street(case.street_query)
        form.wait_street_suggest()
        form.assert_street_not_in_suggest(case.expected_street)
    except Exception:
        screenshot_path = tmp_path / f"{case.case_id}_negative.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        attach_png_file(screenshot_path, "failure_screenshot_negative")
        try:
            debug_state = form.collect_debug_state()
            if debug_state:
                attach_json("form_debug_state_negative", debug_state)
        except Exception:
            pass
        raise
    finally:
        console.stop()
        recorder.stop()
        attach_json("cookies", context.cookies())
        attach_json("network_events", [event.__dict__ for event in recorder.events])
        if case.variant == "B":
            attach_json("network_b_endpoint_summary", recorder.build_b_endpoint_summary())
        attach_json("console_errors", console.errors)
