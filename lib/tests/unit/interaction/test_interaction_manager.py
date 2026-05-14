import pytest

from blue_data_user_source.interaction.manager import InteractionManager


async def test_start_calls_on_start_callback() -> None:
    called: list[str] = []

    async def on_start() -> None:
        called.append("start")

    async def on_response(msg: str) -> str:
        return ""

    async def on_stop() -> None:
        pass

    mgr = InteractionManager(on_start=on_start, on_response=on_response, on_stop=on_stop)
    await mgr.start()
    assert called == ["start"]


async def test_stop_calls_on_stop_callback() -> None:
    called: list[str] = []

    async def on_start() -> None:
        pass

    async def on_response(msg: str) -> str:
        return ""

    async def on_stop() -> None:
        called.append("stop")

    mgr = InteractionManager(on_start=on_start, on_response=on_response, on_stop=on_stop)
    await mgr.stop()
    assert called == ["stop"]


async def test_send_calls_on_response_and_returns_result() -> None:
    async def on_start() -> None:
        pass

    async def on_response(msg: str) -> str:
        return f"response to: {msg}"

    async def on_stop() -> None:
        pass

    mgr = InteractionManager(on_start=on_start, on_response=on_response, on_stop=on_stop)
    result = await mgr.send("do you prefer remote work?")
    assert result == "response to: do you prefer remote work?"


async def test_send_passes_message_verbatim_to_callback() -> None:
    received: list[str] = []

    async def on_start() -> None:
        pass

    async def on_response(msg: str) -> None:
        received.append(msg)

    async def on_stop() -> None:
        pass

    mgr = InteractionManager(on_start=on_start, on_response=on_response, on_stop=on_stop)
    await mgr.send("hello world")
    assert received == ["hello world"]
