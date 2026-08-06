from __future__ import annotations

import time
from typing import Literal

AB_COOKIE_NAME = "testNewAddressPoisk"
YM_UID_COOKIE_NAME = "_ym_uid"


def assert_ab_cookie_absent(context) -> None:
    cookie = get_ab_cookie(context)
    assert cookie is None, f"Expected {AB_COOKIE_NAME} cookie to be absent, but got: {cookie}"


def wait_ab_cookie(context, timeout_ms: int = 10000) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        cookie = get_ab_cookie(context)
        if cookie in {"A", "B"}:
            return cookie
        time.sleep(0.2)
    raise AssertionError(f"{AB_COOKIE_NAME} cookie was not assigned within {timeout_ms}ms")


def get_ab_cookie(context) -> str | None:
    cookies = context.cookies()
    for cookie in cookies:
        if cookie.get("name") == AB_COOKIE_NAME:
            return cookie.get("value")
    return None


def set_ab_cookie(context, url: str, variant: Literal["A", "B"]) -> None:
    context.add_cookies(
        [
            {
                "name": AB_COOKIE_NAME,
                "value": variant,
                "url": url,
            }
        ]
    )


def assert_ab_cookie_value(context, expected: Literal["A", "B"]) -> None:
    actual = get_ab_cookie(context)
    assert actual == expected, f"Expected {AB_COOKIE_NAME}={expected}, got {actual}"


def assert_ab_cookie_not_changed(context, initial_value: str) -> None:
    actual = get_ab_cookie(context)
    assert actual == initial_value, f"Expected cookie value to stay {initial_value}, got {actual}"


def get_ym_uid_cookie(context) -> str | None:
    cookies = context.cookies()
    for cookie in cookies:
        if cookie.get("name") == YM_UID_COOKIE_NAME:
            return cookie.get("value")
    return None
