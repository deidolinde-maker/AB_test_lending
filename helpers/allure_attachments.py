from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import allure
except Exception:  # pragma: no cover
    allure = None


def attach_json(name: str, payload: Any) -> None:
    if allure is None:
        return
    allure.attach(
        json.dumps(payload, ensure_ascii=False, indent=2),
        name=name,
        attachment_type=allure.attachment_type.JSON,
    )


def attach_text(name: str, text: str) -> None:
    if allure is None:
        return
    allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)


def attach_markdown(name: str, text: str) -> None:
    if allure is None:
        return
    allure.attach(text, name=name, attachment_type="text/markdown")


def attach_png_file(path: str | Path, name: str) -> None:
    if allure is None:
        return
    p = Path(path)
    if not p.exists():
        return
    allure.attach.file(str(p), name=name, attachment_type=allure.attachment_type.PNG)


def attach_video_file(path: str | Path, name: str = "video") -> None:
    if allure is None:
        return
    p = Path(path)
    if not p.exists():
        return
    # Playwright pytest stores videos in WebM format.
    allure.attach.file(str(p), name=name, attachment_type="video/webm")


def attach_markdown_file(path: str | Path, name: str) -> None:
    if allure is None:
        return
    p = Path(path)
    if not p.exists():
        return
    allure.attach.file(str(p), name=name, attachment_type="text/markdown")
