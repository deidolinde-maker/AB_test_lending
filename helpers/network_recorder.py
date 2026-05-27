from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlparse


@dataclass
class NetworkEvent:
    case_id: str
    variant: str
    method: str
    url: str
    query_params: dict[str, list[str]]
    status: int | None = None
    response_snippet: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class NetworkRecorder:
    def __init__(self, page, *, case_id: str, variant: str) -> None:
        self.page = page
        self.case_id = case_id
        self.variant = variant
        self.events: list[NetworkEvent] = []

    def start(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def stop(self) -> None:
        self.page.remove_listener("request", self._on_request)
        self.page.remove_listener("response", self._on_response)

    def _on_request(self, request) -> None:
        url = request.url
        parsed = urlparse(url)
        path = parsed.path.lower()
        is_search_like = any(
            marker in path
            for marker in (
                "/search/",
                "/v2/streets",
                "/v2/houses",
                "/streets",
                "/houses",
                "/autocomplete",
                "/suggest",
                "/api_protected/",
                "/cf7proxy/",
                "/cf7proxy/v2/streets",
                "/cf7proxy/v2/houses",
            )
        )
        if not is_search_like:
            return
        self.events.append(
            NetworkEvent(
                case_id=self.case_id,
                variant=self.variant,
                method=request.method,
                url=url,
                query_params=parse_qs(parsed.query),
            )
        )

    def _on_response(self, response) -> None:
        url = response.url
        for event in reversed(self.events):
            if event.url == url and event.status is None:
                event.status = response.status
                try:
                    payload = response.text()
                    event.response_snippet = payload[:10000]
                except Exception:
                    event.response_snippet = None
                break

    @staticmethod
    def _safe_json_loads(text: str | None):
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def build_b_endpoint_summary(self) -> list[dict]:
        summary: list[dict] = []
        for event in self.events:
            lowered = event.url.lower()
            if not any(
                marker in lowered
                for marker in (
                    "/api_protected/v2/search/streets",
                    "/api_protected/v2/search/houses",
                    "/wp-json/cf7proxy/v2/streets",
                    "/wp-json/cf7proxy/v2/houses",
                )
            ):
                continue
            payload = self._safe_json_loads(event.response_snippet)
            payload_type = type(payload).__name__ if payload is not None else None
            payload_preview = None
            if isinstance(payload, dict):
                payload_preview = {k: type(v).__name__ for k, v in list(payload.items())[:8]}
            elif isinstance(payload, list):
                payload_preview = {
                    "list_size": len(payload),
                    "first_item_keys": list(payload[0].keys())[:8]
                    if payload and isinstance(payload[0], dict)
                    else None,
                }
            summary.append(
                {
                    "url": event.url,
                    "method": event.method,
                    "status": event.status,
                    "query_params": event.query_params,
                    "payload_type": payload_type,
                    "payload_preview": payload_preview,
                    "response_snippet": event.response_snippet,
                }
            )
        return summary

    def assert_v2_endpoints_for_b(self) -> None:
        if self.variant != "B":
            return
        urls = [event.url.lower() for event in self.events]
        observed_urls = self._format_observed_search_urls()
        streets_ok = any(
            marker in url
            for marker in (
                "/api_protected/v2/search/streets",
                "/wp-json/cf7proxy/v2/streets",
            )
            for url in urls
        )
        houses_ok = any(
            marker in url
            for marker in (
                "/api_protected/v2/search/houses",
                "/wp-json/cf7proxy/v2/houses",
            )
            for url in urls
        )
        assert streets_ok, (
            "Expected streets request to hit v2 endpoint "
            "(/api_protected/v2/search/streets or /wp-json/cf7proxy/v2/streets). "
            f"Observed search-like URLs: {observed_urls}"
        )
        assert houses_ok, (
            "Expected houses request to hit v2 endpoint "
            "(/api_protected/v2/search/houses or /wp-json/cf7proxy/v2/houses). "
            f"Observed search-like URLs: {observed_urls}"
        )

    def _format_observed_search_urls(self, limit: int = 12) -> list[str]:
        observed: list[str] = []
        seen: set[str] = set()
        for event in self.events:
            url = event.url
            if url in seen:
                continue
            seen.add(url)
            observed.append(url)
            if len(observed) >= limit:
                break
        return observed
