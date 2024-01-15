import re
from typing import Any, TypeVar
from functools import wraps, partial
from typing_extensions import ParamSpec
from collections.abc import Callable, Coroutine

from anyio import to_thread, from_thread

DELIMITERS = r"\. _-"

P = ParamSpec("P")
R = TypeVar("R")


def sanitize(value: str) -> str:
    """Replace every character that isn't 0-9, A-Z, a-z, or a known delimiter"""
    return re.sub(rf"[^\w{DELIMITERS}]+", "_", value)


def split_words(value: str) -> list[str]:
    """Split a string on words and known delimiters"""
    # We can't guess words if there is no capital letter
    if any(c.isupper() for c in value):
        value = " ".join(re.split("([A-Z]?[a-z]+)", value))
    return re.findall(rf"[^{DELIMITERS}]+", value)


def snake_case(value: str) -> str:
    """Converts to snake_case"""
    words = split_words(sanitize(value))
    return "_".join(words).lower()


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
