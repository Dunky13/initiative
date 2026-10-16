"""The app as the server runs it."""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any


def in_request_tasks(app: Any) -> Any:
    """``app`` with each request run in a task of its own, as uvicorn runs it.

    What a request sets in a context variable stays in that request, rather
    than reaching the test that sent it or the next request. The task starts
    from a copy of the test's context, so what a fixture set there is read as
    before.
    """

    async def serve(scope: dict, receive: Any, send: Any) -> None:
        await asyncio.create_task(
            app(scope, receive, send), context=contextvars.copy_context()
        )

    return serve
