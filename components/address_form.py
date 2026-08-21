from __future__ import annotations

import os
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from helpers.selectors import candidate_selectors, first_selector
from models import FormConfig

try:
    SUGGEST_WAIT_TIMEOUT_MS = int(os.getenv("SUGGEST_WAIT_TIMEOUT_MS", "10000"))
except Exception:
    SUGGEST_WAIT_TIMEOUT_MS = 10000

HOUSE_SUGGEST_WAIT_TIMEOUT_MS = max(SUGGEST_WAIT_TIMEOUT_MS, 15000)

SUGGESTION_SELECTORS = [
    "#street-list .autocomplete-item",
    "#house-list .autocomplete-item",
    ".autocomplete-list:not(.hidden) .autocomplete-item",
    ".autocomplete-list.checkaddress__item",
    ".autocomplete-list.checkaddress__item .checkaddress__item",
    ".autocomplete-list.checkaddress__item li",
    "[role='option']",
    "[role='listbox'] li",
    ".suggestions__item",
    ".suggestion-item",
    ".autocomplete__item",
    ".ui-menu-item",
    "[class*='suggest'] li",
    "[class*='autocomplete'] li",
    "[class*='dropdown'] li",
]


class AddressForm:
    def __init__(self, page, form_config: FormConfig) -> None:
        self.page = page
        self.form_config = form_config
        self._last_selected_street: dict | None = None
        self._last_selected_house: dict | None = None

    def _dismiss_blocking_overlays(self) -> None:
        candidates = [
            "#cookieCloud button",
            "#cookieCloud .btn",
            ".cookie-cloud button",
            "[id*='cookie'] button",
            "[class*='cookie'] button",
            "#popup-lead-catcher",
            "[data-tooltip-hook='form']",
            "#popup-select-city .popup__close",
            "#popup-select-city button",
            ".modal__close",
            ".popup__close",
        ]
        for selector in candidates:
            locator = self.page.locator(selector).first
            if locator.count() == 0:
                continue
            try:
                locator.click(timeout=1200)
                self.page.wait_for_timeout(150)
            except Exception:
                try:
                    locator.evaluate(
                        """(el) => {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                            el.style.pointerEvents = 'none';
                        }"""
                    )
                except Exception:
                    continue

    def _first_visible(self, selector: str):
        locator = self.page.locator(selector)
        count = locator.count()
        for idx in range(count):
            candidate = locator.nth(idx)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return locator.first

    def _click_with_fallback(self, selector: str) -> None:
        locator = self._first_visible(selector)
        try:
            locator.click(timeout=4000)
        except PlaywrightTimeoutError:
            self._dismiss_blocking_overlays()
            locator.click(timeout=4000, force=True)

    def _visible_selector_from_config(self, key: str) -> str | None:
        for selector in candidate_selectors(self.form_config.selectors, key):
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                for idx in range(count):
                    candidate = locator.nth(idx)
                    try:
                        if candidate.is_visible():
                            return selector
                    except Exception:
                        continue
            except Exception:
                continue
        return first_selector(self.form_config.selectors, key)

    def open(self) -> None:
        self._dismiss_blocking_overlays()
        # Prefer inline form: if street input is already visible, do not open popup.
        if self.is_present():
            return
        open_keys = ("open", "open_from_cards", "open_popup", "open_if_popup", "inline_form")
        for selector in candidate_selectors(self.form_config.selectors, *open_keys):
            locator = self.page.locator(selector)
            if locator.count() == 0:
                continue
            visible_candidate = None
            for idx in range(locator.count()):
                candidate = locator.nth(idx)
                try:
                    if candidate.is_visible():
                        visible_candidate = candidate
                        break
                except Exception:
                    continue
            if visible_candidate is None:
                continue
            # inline_form indicates that form is already present and no click is needed.
            if selector in candidate_selectors(self.form_config.selectors, "inline_form"):
                return
            try:
                visible_candidate.click(timeout=4000)
            except PlaywrightTimeoutError:
                self._dismiss_blocking_overlays()
                visible_candidate.click(timeout=4000, force=True)
            self.page.wait_for_timeout(250)
            if self.is_present():
                return

    def is_present(self) -> bool:
        street_selector = first_selector(self.form_config.selectors, "street")
        if not street_selector:
            return False
        locator = self._first_visible(street_selector)
        return locator.count() > 0 and locator.is_visible()

    def can_change_city(self) -> bool:
        for selector in self._change_city_selectors():
            try:
                locator = self._first_visible(selector)
                if locator.count() > 0 and locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    def change_city_inside_form(self, region: str) -> None:
        for selector in self._change_city_selectors():
            candidates = self.page.locator(selector)
            count = candidates.count()
            if count == 0:
                continue

            for idx in range(count):
                trigger = candidates.nth(idx)
                try:
                    if not trigger.is_visible():
                        continue
                    trigger.click(timeout=4000, force=True)
                    self.page.wait_for_timeout(600)
                except Exception:
                    continue

                if self._is_city_popup_visible():
                    self._fill_city_input_in_popup(region)
                    self.page.wait_for_timeout(400)
                    if self._click_city_link_in_popup(region):
                        return

                if self._click_city_link(region):
                    return
                self._fill_city_input_once(region)
                self.page.wait_for_timeout(500)
                if self._click_city_link(region):
                    return
                try:
                    self._click_visible_text(region, timeout_ms=1200)
                    return
                except Exception:
                    continue

        raise AssertionError(f"Failed to change city inside form to '{region}'")

    def _change_city_selectors(self) -> list[str]:
        selectors: list[str] = []
        configured = first_selector(self.form_config.selectors, "change_city")
        if configured:
            selectors.append(configured)
        selectors.extend(
            [
                ".button-select-city",
                ".autocomplete-city-change",
                ".autocomplete-city-change-wrapper .button-select-city",
                ".autocomplete-city-wrapper .button-select-city",
            ]
        )
        # Preserve order and uniqueness.
        dedup: list[str] = []
        seen: set[str] = set()
        for sel in selectors:
            if sel in seen:
                continue
            seen.add(sel)
            dedup.append(sel)
        return dedup

    def _is_city_popup_visible(self) -> bool:
        popup = self.page.locator("#popup-select-city").first
        return popup.count() > 0 and popup.is_visible()

    def _fill_city_input_in_popup(self, city_name: str) -> bool:
        popup_inputs = [
            "#popup-select-city #city-input",
            "#popup-select-city input.popup-select-city__input",
            "#popup-select-city input[placeholder=' ']",
        ]
        for sel in popup_inputs:
            try:
                inp = self.page.locator(sel).first
                if inp.count() == 0 or not inp.is_visible():
                    continue
                inp.click(force=True)
                inp.fill(city_name)
                return True
            except Exception:
                continue
        return False

    def _click_city_link_in_popup(self, city_name: str) -> bool:
        popup_link_selectors = [
            "#popup-select-city .region_item.region_link",
            "#popup-select-city .region_item",
            "#popup-select-city .city_list a",
        ]
        for sel in popup_link_selectors:
            try:
                links = self.page.locator(sel).filter(has_text=city_name)
                for idx in range(links.count()):
                    link = links.nth(idx)
                    try:
                        if not link.is_visible():
                            continue
                        link.scroll_into_view_if_needed()
                        link.click(timeout=3000, force=True)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def fill_street(self, value: str) -> None:
        self._dismiss_blocking_overlays()
        selector = first_selector(self.form_config.selectors, "street")
        street_input = self._first_visible(selector)
        street_input.scroll_into_view_if_needed()
        street_input.click(force=True)
        try:
            street_input.fill("")
        except Exception:
            pass
        street_input.fill(value)

    def wait_street_suggest(self) -> None:
        self._wait_for_visible_suggest_items("#street-list", timeout_ms=SUGGEST_WAIT_TIMEOUT_MS)

    def _has_visible_text(self, text: str) -> bool:
        locator = self.page.get_by_text(text, exact=False)
        count = locator.count()
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if item.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _collect_visible_suggest_items(self, root_selector: str, limit: int = 30) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        selectors = [root_selector]
        if root_selector in {"#street-list", "#house-list"}:
            selectors = [
                root_selector,
                f"{root_selector}.checkaddress__item",
                f"{root_selector} .autocomplete-item",
                f"{root_selector} .checkaddress__item",
                ".autocomplete-list:not(.hidden) .autocomplete-item",
                ".autocomplete-list.checkaddress__item",
                ".autocomplete-list.checkaddress__item .checkaddress__item",
                ".autocomplete-list.checkaddress__item li",
            ]
            selectors.extend(SUGGESTION_SELECTORS[3:])
        for selector in selectors:
            try:
                items = self.page.locator(selector)
            except Exception:
                continue
            for idx in range(items.count()):
                item = items.nth(idx)
                try:
                    if not item.is_visible():
                        continue
                    text = " ".join((item.inner_text() or "").split()).strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    result.append(text)
                    if len(result) >= limit:
                        return result
                except Exception:
                    continue
        return result

    def _wait_for_visible_suggest_items(self, root_selector: str, timeout_ms: int) -> list[str]:
        deadline = time.monotonic() + timeout_ms / 1000
        last_items: list[str] = []
        while time.monotonic() < deadline:
            last_items = self._collect_visible_suggest_items(root_selector)
            if last_items:
                return last_items
            time.sleep(0.3)
        return last_items

    @staticmethod
    def _norm_house(value: str) -> str:
        out = value.lower().replace(" ", "")
        out = out.replace("корпус", "к")
        out = out.replace("к.", "к")
        out = out.replace("/", "к")
        return out

    @staticmethod
    def _norm_text(value: str) -> str:
        return " ".join((value or "").strip().lower().replace("ё", "е").split())

    @classmethod
    def _strip_street_prefix(cls, value: str) -> str:
        text = cls._norm_text(value)
        for prefix in ("ул ", "ул.", "улица "):
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    def _is_region_match(self, city_text: str, preferred_region: str | None) -> bool:
        if not preferred_region:
            return True
        return self._norm_text(preferred_region) in self._norm_text(city_text)

    def _is_domodedovo_oblast_alias_match(self, city_text: str, preferred_region: str | None) -> bool:
        if not preferred_region:
            return False
        preferred = self._norm_text(preferred_region)
        city = self._norm_text(city_text)
        return "домодедов" in preferred and "московская область" in city

    def _is_address_context_match(
        self,
        city_text: str,
        preferred_region: str | None,
        preferred_locality: str | None = None,
        allow_domodedovo_oblast_alias: bool = False,
    ) -> bool:
        """Match the whole visible locality context, not only a region substring."""
        if not preferred_region:
            return True

        normalized_city = self._norm_text(city_text)
        normalized_region = self._norm_text(preferred_region)
        normalized_locality = self._norm_text(preferred_locality or "")
        parts = [part.strip() for part in normalized_city.split(",") if part.strip()]
        address_parts = [
            part
            for part in parts
            if not part.endswith((" область", " край", " республика"))
        ]

        def without_admin_prefix(value: str) -> str:
            for prefix in ("г ", "город "):
                if value.startswith(prefix):
                    return value[len(prefix) :].strip()
            return value

        region_part_matches = any(
            without_admin_prefix(part) == normalized_region for part in parts
        )
        if normalized_locality:
            locality_matches = normalized_locality in normalized_city
            return locality_matches and (
                region_part_matches
                or (
                    allow_domodedovo_oblast_alias
                    and self._is_domodedovo_oblast_alias_match(city_text, preferred_region)
                )
            )

        # Reject a more specific alias such as "г Балашиха, мкр Саввино"
        # when the case expects the city without an additional locality.
        if region_part_matches:
            return len(address_parts) == 1

        return allow_domodedovo_oblast_alias and self._is_domodedovo_oblast_alias_match(
            city_text, preferred_region
        )

    def _is_strict_street_match(self, street_text: str, expected: str) -> bool:
        st = self._strip_street_prefix(street_text)
        exp = self._strip_street_prefix(expected)
        if st == exp:
            return True
        if not st.startswith(exp):
            return False
        suffix = st[len(exp):].strip()
        # Accept only direct street suffix, reject qualifiers like "(Салтыковка)".
        return suffix in {"", "ул", "ул.", "улица"}

    def _collect_street_rows(self) -> list[tuple[object, str, str]]:
        rows: list[tuple[object, str, str]] = []
        street_items = self.page.locator("#street-list .autocomplete-item")
        if street_items.count() == 0:
            street_items = self.page.locator(".autocomplete-list:not(.hidden) .autocomplete-item")
        if street_items.count() == 0:
            street_items = self.page.locator(".autocomplete-list.checkaddress__item .checkaddress__item")
        if street_items.count() == 0:
            street_items = self.page.locator(".autocomplete-list.checkaddress__item li")
        for idx in range(street_items.count()):
            item = street_items.nth(idx)
            try:
                if not item.is_visible():
                    continue
                street_text = (
                    item.locator(".autocomplete-street").first.inner_text()
                    if item.locator(".autocomplete-street").count() > 0
                    else item.inner_text()
                )
                city_text = (
                    item.locator(".autocomplete-city").first.inner_text()
                    if item.locator(".autocomplete-city").count() > 0
                    else ""
                )
                street_lines = [line.strip() for line in (street_text or "").splitlines() if line.strip()]
                if street_lines:
                    street_text = street_lines[0]
                    if not city_text and len(street_lines) > 1:
                        city_text = " ".join(street_lines[1:])
                city_lines = [line.strip() for line in (city_text or "").splitlines() if line.strip()]
                if city_lines:
                    city_text = " ".join(city_lines)
                rows.append((item, street_text or "", city_text or ""))
            except Exception:
                continue
        return rows

    def _street_rank(self, street_text: str, expected: str) -> tuple[int, int]:
        st = self._strip_street_prefix(street_text)
        exp = self._strip_street_prefix(expected)
        exact = 0 if st == exp or st in {f"{exp} ул", f"{exp} ул.", f"{exp} улица"} else 1
        return (exact, len(st))

    def _click_visible_text(self, text: str, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            locator = self.page.get_by_text(text, exact=False)
            count = locator.count()
            for idx in range(count):
                item = locator.nth(idx)
                try:
                    if not item.is_visible():
                        continue
                    item.click(timeout=1500)
                    return
                except Exception as exc:
                    last_error = exc
                    continue
            time.sleep(0.2)
        if last_error:
            raise last_error
        raise AssertionError(f"Visible text target was not found: {text}")

    def _fill_city_input_once(self, city_name: str) -> bool:
        city_input_selectors = [
            "xpath=//input[@placeholder='Введите название города']",
            "xpath=//input[@id='city-input']",
            "xpath=//input[@placeholder='Поиск города']",
            "xpath=//input[@placeholder='Город']",
            "input[name='city']",
            "input[placeholder*='оиск']",
            "input[placeholder*='ород']",
            "input[type='search']",
        ]

        for sel in city_input_selectors:
            try:
                inputs = self.page.locator(sel)
                for idx in range(inputs.count()):
                    inp = inputs.nth(idx)
                    try:
                        if not inp.is_visible():
                            continue
                        inp.click(force=True)
                        inp.fill(city_name)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def _click_city_link(self, city_name: str) -> bool:
        city_link_selectors = [
            "xpath=(//a[@class='region_item region_link'])",
            "xpath=//a[@class='region_item']",
            "xpath=//div[@class='city-coverage__capital']//a",
            "xpath=(//table[@class='city_list']//tbody//tr//td//a)",
            ".region_item.region_link",
            ".region_item",
        ]

        for sel in city_link_selectors:
            try:
                links = self.page.locator(sel).filter(has_text=city_name)
                for idx in range(links.count()):
                    link = links.nth(idx)
                    try:
                        if not link.is_visible():
                            continue
                        link.scroll_into_view_if_needed()
                        link.click(timeout=3000, force=True)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def assert_street_in_suggest(self, expected: str, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            items = self._wait_for_visible_suggest_items("#street-list", timeout_ms=300)
            if any(
                self._is_strict_street_match(item, expected)
                or self._strip_street_prefix(expected) in self._strip_street_prefix(item)
                for item in items
            ):
                return
            time.sleep(0.3)
        street_items = self._collect_visible_suggest_items("#street-list")
        raise AssertionError(
            f"Expected street in suggest: {expected}. Visible street suggestions: {street_items}"
        )

    def assert_street_not_in_suggest(self, unexpected: str, forbidden_region: str | None = None) -> None:
        rows = self._collect_street_rows()
        for _, street_text, city_text in rows:
            if not self._is_strict_street_match(street_text, unexpected):
                continue
            if not self._is_region_match(city_text, forbidden_region):
                continue
            raise AssertionError(
                f"Unexpected street in suggest: {unexpected}. "
                f"Matched row: street='{street_text}', city='{city_text}'"
            )
        if not rows:
            # Fallback if suggestion rows are not visible as structured list.
            assert not self._has_visible_text(unexpected), f"Unexpected street in suggest: {unexpected}"

    def select_street(
        self,
        expected: str,
        preferred_region: str | None = None,
        preferred_locality: str | None = None,
        allow_domodedovo_oblast_alias: bool = False,
    ) -> None:
        self._last_selected_street = None
        self._dismiss_blocking_overlays()
        street_rows = self._collect_street_rows()
        if street_rows:
            strict_rows = [row for row in street_rows if self._is_strict_street_match(row[1], expected)]
            if strict_rows:
                region_rows = []
                for row in strict_rows:
                    if self._is_address_context_match(
                        row[2],
                        preferred_region,
                        preferred_locality,
                        allow_domodedovo_oblast_alias,
                    ):
                        region_rows.append(row)
                        continue
                    if allow_domodedovo_oblast_alias and self._is_domodedovo_oblast_alias_match(
                        row[2], preferred_region
                    ):
                        region_rows.append(row)
                if preferred_region and not region_rows:
                    visible = self._collect_visible_suggest_items("#street-list")
                    strict_debug = [
                        {"street": row[1], "city": row[2]}
                        for row in strict_rows[:10]
                    ]
                    raise AssertionError(
                        f"Street '{expected}' was found, but not for region '{preferred_region}'. "
                        f"Strict matches: {strict_debug}. Visible street suggestions: {visible}"
                    )
                candidate_pool = region_rows or strict_rows
                best_item, best_street, best_city = min(
                    candidate_pool,
                    key=lambda row: self._street_rank(row[1], expected),
                )
                self._dismiss_blocking_overlays()
                best_item.click(timeout=3000, force=True)
                self.page.wait_for_timeout(250)
                self._last_selected_street = {
                    "expected": expected,
                    "preferred_region": preferred_region,
                    "preferred_locality": preferred_locality,
                    "selected_street": best_street,
                    "selected_city": best_city,
                    "strategy": "street_list_strict",
                }
                return

            if preferred_region:
                visible = self._collect_visible_suggest_items("#street-list")
                raise AssertionError(
                    f"Street '{expected}' for region '{preferred_region}' was not found as strict suggest match. "
                    f"Visible street suggestions: {visible}"
                )

        street_selector = first_selector(self.form_config.selectors, "street")
        if street_selector:
            street_input = self._first_visible(street_selector)
            try:
                self._dismiss_blocking_overlays()
                street_input.click(timeout=2000, force=True)
                street_input.press("ArrowDown")
                street_input.press("Enter")
                self.page.wait_for_timeout(250)
                if self.is_house_field_ready():
                    self._last_selected_street = {
                        "expected": expected,
                        "preferred_region": preferred_region,
                        "strategy": "keyboard_arrowdown_enter",
                    }
                    return
            except Exception:
                pass

        locator = self.page.get_by_text(expected, exact=False).first
        try:
            self._dismiss_blocking_overlays()
            locator.click(timeout=4000)
        except PlaywrightTimeoutError:
            self._dismiss_blocking_overlays()
            try:
                locator.click(timeout=4000, force=True)
            except PlaywrightTimeoutError:
                if not street_selector:
                    raise
                street_input = self._first_visible(street_selector)
                self._dismiss_blocking_overlays()
                street_input.click(timeout=2000, force=True)
                street_input.press("ArrowDown")
                street_input.press("Enter")
                self._last_selected_street = {
                    "expected": expected,
                    "preferred_region": preferred_region,
                    "strategy": "fallback_keyboard_after_text_click_timeout",
                }
                return
        self._last_selected_street = {
            "expected": expected,
            "preferred_region": preferred_region,
            "strategy": "text_click",
        }

        if not self.is_house_field_ready():
            street_selector = first_selector(self.form_config.selectors, "street")
            if street_selector:
                street_input = self._first_visible(street_selector)
                self._dismiss_blocking_overlays()
                street_input.click(force=True)
                street_input.press("ArrowDown")
                street_input.press("Enter")

    def try_select_street(
        self,
        expected: str,
        preferred_region: str | None = None,
        preferred_locality: str | None = None,
        allow_domodedovo_oblast_alias: bool = False,
    ) -> bool:
        self._last_selected_street = None
        self._dismiss_blocking_overlays()
        street_rows = self._collect_street_rows()
        if not street_rows:
            return False

        strict_rows = [row for row in street_rows if self._is_strict_street_match(row[1], expected)]
        if not strict_rows:
            return False

        candidate_pool = strict_rows
        if preferred_region:
            region_rows = []
            for row in strict_rows:
                if self._is_address_context_match(
                    row[2],
                    preferred_region,
                    preferred_locality,
                    allow_domodedovo_oblast_alias,
                ):
                    region_rows.append(row)
                    continue
                if allow_domodedovo_oblast_alias and self._is_domodedovo_oblast_alias_match(
                    row[2], preferred_region
                ):
                    region_rows.append(row)
            if not region_rows:
                return False
            candidate_pool = region_rows

        best_item, best_street, best_city = min(
            candidate_pool,
            key=lambda row: self._street_rank(row[1], expected),
        )
        self._dismiss_blocking_overlays()
        best_item.click(timeout=3000, force=True)
        self.page.wait_for_timeout(250)
        self._last_selected_street = {
            "expected": expected,
            "preferred_region": preferred_region,
            "preferred_locality": preferred_locality,
            "selected_street": best_street,
            "selected_city": best_city,
            "strategy": "street_list_strict_try",
        }
        return True

    def fill_house(self, value: str) -> None:
        selector = self._visible_selector_from_config("house")
        if not selector:
            raise AssertionError("House selector is missing")

        last_error: Exception | None = None
        for attempt in range(2):
            self._dismiss_blocking_overlays()
            try:
                self.wait_house_field_ready(timeout_ms=8000 if attempt == 0 else 15000)
                house_input = self._first_visible(selector)
                house_input.scroll_into_view_if_needed()
                house_input.click(force=True)
                try:
                    house_input.fill("")
                except Exception:
                    pass
                house_input.fill(value)
                self.page.wait_for_timeout(400)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0 and self._reselect_last_street():
                    self.page.wait_for_timeout(400)
                    continue
                break

        if last_error is not None:
            raise last_error
        self.wait_house_field_ready()
        self._first_visible(selector).fill(value)

    def wait_house_suggest(self) -> None:
        self._wait_for_visible_suggest_items("#house-list", timeout_ms=HOUSE_SUGGEST_WAIT_TIMEOUT_MS)

    def assert_house_in_suggest(self, expected: str, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            items = self._wait_for_visible_suggest_items("#house-list", timeout_ms=300)
            if any(self._norm_house(expected) in self._norm_house(item) for item in items):
                return
            time.sleep(0.3)
        house_items = self._collect_visible_suggest_items("#house-list")
        expected_norm = self._norm_house(expected)
        has_format_near_match = any(expected_norm in self._norm_house(item) for item in house_items)
        if has_format_near_match:
            raise AssertionError(
                f"Expected house in suggest: {expected}. "
                f"Near format match exists, visible house suggestions: {house_items}"
            )
        raise AssertionError(
            f"Expected house in suggest: {expected}. Visible house suggestions: {house_items}"
        )

    def assert_house_not_in_suggest(self, unexpected: str) -> None:
        unexpected_norm = self._norm_house(unexpected)
        visible_house_suggestions = self._collect_visible_suggest_items("#house-list")
        if visible_house_suggestions:
            for item in visible_house_suggestions:
                item_main = (item or "").splitlines()[0].strip()
                if self._norm_house(item_main) == unexpected_norm:
                    raise AssertionError(
                        f"Unexpected house in suggest: {unexpected}. "
                        f"Matched house item: '{item_main}'"
                    )
            return
        assert not self._has_visible_text(unexpected), f"Unexpected house in suggest: {unexpected}"

    def select_house(self, expected: str) -> None:
        self._last_selected_house = None
        self._dismiss_blocking_overlays()
        house_items = self.page.locator("#house-list .autocomplete-item")
        if house_items.count() == 0:
            house_items = self.page.locator(".autocomplete-list:not(.hidden) .autocomplete-item")
        if house_items.count() == 0:
            house_items = self.page.locator(".autocomplete-list.checkaddress__item .checkaddress__item")
        if house_items.count() == 0:
            house_items = self.page.locator(".autocomplete-list.checkaddress__item li")
        if house_items.count() > 0:
            expected_norm = self._norm_house(expected)
            exact_item = None
            near_item = None
            fallback_item = None
            for idx in range(house_items.count()):
                item = house_items.nth(idx)
                try:
                    if not item.is_visible():
                        continue
                    text = (item.inner_text() or "").strip()
                    if not text:
                        continue
                    if fallback_item is None:
                        fallback_item = (item, text)
                    if text == expected:
                        exact_item = (item, text)
                        break
                    if expected_norm == self._norm_house(text) and near_item is None:
                        near_item = (item, text)
                except Exception:
                    continue

            picked = exact_item or near_item or fallback_item
            if picked is not None:
                picked_item, picked_text = picked
                self._dismiss_blocking_overlays()
                picked_item.click(timeout=3000, force=True)
                self.page.wait_for_timeout(250)
                self._last_selected_house = {
                    "expected": expected,
                    "selected_house_text": picked_text,
                    "strategy": (
                        "house_list_exact"
                        if exact_item is not None
                        else "house_list_normalized"
                        if near_item is not None
                        else "house_list_fallback_first_visible"
                    ),
                }
                return

        house_selector = first_selector(self.form_config.selectors, "house")
        if house_selector:
            house_input = self._first_visible(house_selector)
            try:
                self._dismiss_blocking_overlays()
                house_input.click(timeout=2000, force=True)
                house_input.press("ArrowDown")
                house_input.press("Enter")
                self.page.wait_for_timeout(250)
                self._last_selected_house = {
                    "expected": expected,
                    "strategy": "keyboard_arrowdown_enter",
                }
                return
            except Exception:
                pass

        locator = self.page.get_by_text(expected, exact=False).first
        try:
            self._dismiss_blocking_overlays()
            locator.click(timeout=4000)
        except PlaywrightTimeoutError:
            self._dismiss_blocking_overlays()
            locator.click(timeout=4000, force=True)
        self._last_selected_house = {
            "expected": expected,
            "strategy": "text_click",
        }

    def get_selected_house_id(self) -> str | int | None:
        house_selector = self._visible_selector_from_config("house")
        if not house_selector:
            return None
        house_locator = self._first_visible(house_selector)
        if house_locator.count() == 0:
            return None

        # IMPORTANT:
        # Return only house/address identifiers here.
        # Street identifiers (IStreet/id_street) must not be used as selected house ID.
        for selector in (
            "input[name='house_id']",
            "input[name='address_id']",
            "input[name='IHouse']",
            "input#house",
        ):
            try:
                value = house_locator.evaluate(
                    """(el, sel) => {
                        const form = el.closest('form');
                        if (!form) return null;
                        const node = form.querySelector(sel);
                        if (!node) return null;
                        return node.value || null;
                    }""",
                    selector,
                )
            except Exception:
                value = None
            if value:
                return value
        return None

    def get_selected_street_id(self) -> str | int | None:
        street_selector = first_selector(self.form_config.selectors, "street")
        if not street_selector:
            return None
        street_locator = self._first_visible(street_selector)
        if street_locator.count() == 0:
            return None
        for selector in (
            "input[name='street_id']",
            "input[name='IStreet']",
            "input#id_street",
        ):
            try:
                value = street_locator.evaluate(
                    """(el, sel) => {
                        const form = el.closest('form');
                        if (!form) return null;
                        const node = form.querySelector(sel);
                        if (!node) return null;
                        return node.value || null;
                    }""",
                    selector,
                )
            except Exception:
                value = None
            if value:
                return value
        try:
            value = street_locator.get_attribute("data-street-id")
        except Exception:
            value = None
        if value:
            return value
        return None

    def is_house_field_ready(self) -> bool:
        selector = self._visible_selector_from_config("house")
        if not selector:
            return False
        locator = self._first_visible(selector)
        if locator.count() == 0:
            return False
        disabled_attr = locator.get_attribute("disabled")
        readonly_attr = locator.get_attribute("readonly")
        return disabled_attr is None and readonly_attr is None

    def _reselect_last_street(self) -> bool:
        selected = self._last_selected_street or {}
        expected = selected.get("expected")
        if not expected:
            return False
        preferred_region = selected.get("preferred_region")
        allow_alias = bool(preferred_region and "домодедов" in self._norm_text(str(preferred_region)))
        try:
            self.select_street(
                str(expected),
                preferred_region=str(preferred_region) if preferred_region else None,
                allow_domodedovo_oblast_alias=allow_alias,
            )
            return True
        except Exception:
            return False

    def wait_house_field_ready(self, timeout_ms: int = 15000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self.is_house_field_ready():
                return
            time.sleep(0.2)
        selector = self._visible_selector_from_config("house")
        attrs = {}
        if selector:
            locator = self._first_visible(selector)
            if locator.count() > 0:
                attrs = {
                    "disabled": locator.get_attribute("disabled"),
                    "readonly": locator.get_attribute("readonly"),
                    "value": locator.input_value(),
                }
        raise AssertionError(f"House input did not become editable. Details: {attrs}")

    def get_form_dom_snapshot(self) -> str:
        selector = first_selector(self.form_config.selectors, "street")
        if not selector:
            return ""
        return self._first_visible(selector).evaluate("el => el.closest('form')?.outerHTML || ''")

    def collect_debug_state(self) -> dict:
        selector = first_selector(self.form_config.selectors, "street")
        if not selector:
            return {}
        locator = self._first_visible(selector)
        if locator.count() == 0:
            return {}
        try:
            data = locator.evaluate(
                """(el) => {
                    const form = el.closest('form');
                    if (!form) return {};
                    const read = (sel) => {
                        const n = form.querySelector(sel);
                        if (!n) return null;
                        if ('value' in n) return n.value;
                        return (n.innerText || n.textContent || '').trim();
                    };
                    const collectItems = (rootSel) => {
                        const root = form.querySelector(rootSel) || document.querySelector(rootSel);
                        if (!root) return [];
                        const style = getComputedStyle(root);
                        const rootVisible = style.display !== 'none' && style.visibility !== 'hidden';
                        if (!rootVisible) return [];
                        const items = [];
                        const rows = root.querySelectorAll('.autocomplete-item');
                        for (const row of rows) {
                            const rs = row.getBoundingClientRect();
                            const cs = getComputedStyle(row);
                            if (cs.display === 'none' || cs.visibility === 'hidden' || rs.width < 20 || rs.height < 8) continue;
                            items.push((row.innerText || '').trim());
                            if (items.length >= 25) break;
                        }
                        return items;
                    };
                    const cityPopup = document.querySelector('#popup-select-city');
                    const cityPopupVisible = !!cityPopup && (() => {
                        const st = getComputedStyle(cityPopup);
                        const r = cityPopup.getBoundingClientRect();
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    })();
                    return {
                        street_value: read('.checkaddress_address_street'),
                        house_value: read('.checkaddress_address_house'),
                        phone_value: read('.checkaddress_address_phone'),
                        hidden_ids: {
                            IHouse: read(\"input[name='IHouse']\"),
                            IStreet: read(\"input[name='IStreet']\"),
                            house_id: read(\"input[name='house_id']\"),
                            address_id: read(\"input[name='address_id']\"),
                            house: read('input#house'),
                            id_street: read('input#id_street'),
                        },
                        street_suggest_items: collectItems('#street-list'),
                        house_suggest_items: collectItems('#house-list'),
                        city_popup_visible: cityPopupVisible,
                        city_input_value: cityPopup ? (() => {
                            const inp = cityPopup.querySelector('#city-input') || cityPopup.querySelector('input.popup-select-city__input');
                            return inp && 'value' in inp ? inp.value : null;
                        })() : null
                    };
                }"""
            )
            if not isinstance(data, dict):
                return {}
            data["selected_debug"] = {
                "street": self._last_selected_street,
                "house": self._last_selected_house,
            }
            return data
        except Exception:
            return {}
