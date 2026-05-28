from __future__ import annotations

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from helpers.selectors import candidate_selectors, first_selector
from models import FormConfig


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
        selector = first_selector(self.form_config.selectors, "street")
        self._first_visible(selector).fill(value)

    def wait_street_suggest(self) -> None:
        self.page.wait_for_timeout(600)

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
        root = self.page.locator(root_selector).first
        if root.count() == 0 or not root.is_visible():
            # Fallback for forms that use generic autocomplete container ids/classes.
            if root_selector in {"#street-list", "#house-list"}:
                root = self.page.locator(".autocomplete-list:not(.hidden)").first
            if root.count() == 0 or not root.is_visible():
                return []
        items = root.locator(".autocomplete-item")
        result: list[str] = []
        for idx in range(items.count()):
            item = items.nth(idx)
            try:
                if not item.is_visible():
                    continue
                text = (item.inner_text() or "").strip()
                if not text:
                    continue
                result.append(text)
                if len(result) >= limit:
                    break
            except Exception:
                continue
        return result

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

    def _is_region_match(self, city_text: str, preferred_region: str | None) -> bool:
        if not preferred_region:
            return True
        return self._norm_text(preferred_region) in self._norm_text(city_text)

    def _is_strict_street_match(self, street_text: str, expected: str) -> bool:
        st = self._norm_text(street_text)
        exp = self._norm_text(expected)
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
                rows.append((item, street_text or "", city_text or ""))
            except Exception:
                continue
        return rows

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

    def assert_street_in_suggest(self, expected: str, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._has_visible_text(expected):
                return
            time.sleep(0.2)
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

    def select_street(self, expected: str, preferred_region: str | None = None) -> None:
        self._last_selected_street = None
        street_rows = self._collect_street_rows()
        if street_rows:
            strict_rows = [row for row in street_rows if self._is_strict_street_match(row[1], expected)]
            if strict_rows:
                region_rows = [
                    row for row in strict_rows if self._is_region_match(row[2], preferred_region)
                ]
                candidate_pool = region_rows or strict_rows

                def _street_rank(street_text: str) -> tuple[int, int]:
                    st = self._norm_text(street_text)
                    exp = self._norm_text(expected)
                    exact = 0 if st == exp or st in {f"{exp} ул", f"{exp} ул.", f"{exp} улица"} else 1
                    return (exact, len(st))

                best_item, best_street, best_city = min(candidate_pool, key=lambda row: _street_rank(row[1]))
                best_item.click(timeout=3000, force=True)
                self.page.wait_for_timeout(250)
                self._last_selected_street = {
                    "expected": expected,
                    "preferred_region": preferred_region,
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
                street_input.click(timeout=2000)
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
            locator.click(timeout=4000)
        except PlaywrightTimeoutError:
            self._dismiss_blocking_overlays()
            try:
                locator.click(timeout=4000, force=True)
            except PlaywrightTimeoutError:
                if not street_selector:
                    raise
                street_input = self._first_visible(street_selector)
                street_input.click(timeout=2000)
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
                street_input.click()
                street_input.press("ArrowDown")
                street_input.press("Enter")

    def fill_house(self, value: str) -> None:
        self.wait_house_field_ready()
        selector = first_selector(self.form_config.selectors, "house")
        self._first_visible(selector).fill(value)

    def wait_house_suggest(self) -> None:
        self.page.wait_for_timeout(600)

    def assert_house_in_suggest(self, expected: str, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._has_visible_text(expected):
                return
            time.sleep(0.2)
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
        assert not self._has_visible_text(unexpected), f"Unexpected house in suggest: {unexpected}"

    def select_house(self, expected: str) -> None:
        self._last_selected_house = None
        house_items = self.page.locator("#house-list .autocomplete-item")
        if house_items.count() == 0:
            house_items = self.page.locator(".autocomplete-list:not(.hidden) .autocomplete-item")
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
            locator.click(timeout=4000)
        except PlaywrightTimeoutError:
            self._dismiss_blocking_overlays()
            locator.click(timeout=4000, force=True)
        self._last_selected_house = {
            "expected": expected,
            "strategy": "text_click",
        }

    def get_selected_house_id(self) -> str | int | None:
        house_selector = first_selector(self.form_config.selectors, "house")
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

    def is_house_field_ready(self) -> bool:
        selector = first_selector(self.form_config.selectors, "house")
        if not selector:
            return False
        locator = self._first_visible(selector)
        if locator.count() == 0:
            return False
        disabled_attr = locator.get_attribute("disabled")
        readonly_attr = locator.get_attribute("readonly")
        return disabled_attr is None

    def wait_house_field_ready(self, timeout_ms: int = 8000) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self.is_house_field_ready():
                return
            time.sleep(0.2)
        selector = first_selector(self.form_config.selectors, "house")
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
