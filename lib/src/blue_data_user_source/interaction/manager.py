from typing import Any, Callable, Awaitable


class InteractionManager:
    """Manages a single interaction with the user through a specific contact channel."""

    def __init__(
        self,
        on_start: Callable[[], Awaitable[None]],
        on_response: Callable[[str], Awaitable[Any]],
        on_stop: Callable[[], Awaitable[None]],
    ) -> None:
        self._on_start = on_start
        self._on_response = on_response
        self._on_stop = on_stop

    async def start(self) -> None:
        """Start the interaction."""
        await self._on_start()

    async def stop(self) -> None:
        """End the interaction."""
        await self._on_stop()

    async def send(self, message: str, blocking: bool = True) -> Any:
        """Send a message to the user and optionally wait for a response."""
        return await self._on_response(message)
