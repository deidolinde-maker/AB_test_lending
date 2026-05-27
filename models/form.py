from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FormConfig:
    name: str
    site_title: str
    participates_in_ab_search_iteration_1: bool
    optional: bool
    selectors: dict[str, Any]
    behavior: dict[str, Any]

