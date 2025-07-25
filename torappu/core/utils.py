from collections.abc import Callable, Coroutine
from functools import partial, wraps
from typing import Any, TypeVar
from typing_extensions import ParamSpec

from anyio import from_thread, to_thread

DELIMITERS = r"\. _-"

P = ParamSpec("P")
R = TypeVar("R")


def run_sync(func: Callable[P, R]) -> Callable[P, Coroutine[Any, Any, R]]:
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await to_thread.run_sync(partial(func, *args, **kwargs))

    return wrapper


def run_async(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return from_thread.run(partial(func, *args, **kwargs))

    return wrapper
