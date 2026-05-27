from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SiteConfig:
    name: str
    title: str
    enabled: bool
    urls: dict[str, str]
    expected_regions: dict[str, str | None]
    allowed_region_pool: list[str]
    regional_navigation_chain: list[dict[str, Any]]
    required_forms_by_url_type: dict[str, list[str]]
