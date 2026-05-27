from __future__ import annotations


class ConsoleRecorder:
    def __init__(self, page) -> None:
        self.page = page
        self.errors: list[str] = []

    def start(self) -> None:
        self.page.on("console", self._on_console)

    def stop(self) -> None:
        self.page.remove_listener("console", self._on_console)

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            self.errors.append(msg.text)

