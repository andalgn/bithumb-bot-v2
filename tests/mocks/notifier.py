"""MockNotifier — NotificationSender Protocol 구현체."""

from __future__ import annotations


class MockNotifier:
    """알림을 캡처하는 Mock."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, text: str, channel: str = "system") -> bool:
        """알림을 기록하고 True를 반환한다."""
        self.messages.append((channel, text))
        return True
