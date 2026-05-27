from __future__ import annotations

from models import SiteConfig


class LandingPage:
    def __init__(self, page, site_config: SiteConfig) -> None:
        self.page = page
        self.site_config = site_config

    def open(self, url_type: str) -> None:
        self.page.goto(self.site_config.urls[url_type], wait_until="domcontentloaded")

    def get_current_url(self) -> str:
        return self.page.url

    def get_current_region_text(self) -> str:
        # Placeholder selector; уточняется под реальную верстку.
        locator = self.page.locator("[data-testid='region-name'], .region-name, .current-region").first
        if locator.count() == 0:
            return ""
        return locator.inner_text().strip()

    def open_region_selector(self) -> None:
        trigger = self.page.locator("[data-testid='region-selector'], .region-selector, .change-region").first
        trigger.click()

    def select_region_from_page_navigation(self, region: str) -> None:
        self.open_region_selector()
        self.page.get_by_text(region, exact=False).first.click()

    def assert_url_is_expected(self, expected_url: str) -> None:
        actual = self.get_current_url()
        assert actual.rstrip("/") == expected_url.rstrip("/"), (
            f"Expected URL: {expected_url}\nActual URL: {actual}"
        )

    def assert_region_is_expected(self, expected_region: str | None) -> None:
        if expected_region is None:
            return
        actual = self.get_current_region_text()
        assert expected_region.lower() in actual.lower(), (
            f"Expected region: {expected_region}\nActual region: {actual}"
        )
