from collections.abc import Awaitable, Callable, Iterable

import anyio


async def amap[T, R](func: Callable[[T], Awaitable[R]], items: Iterable[T]) -> list[R]:
    """Await ``func(item)`` for every item concurrently; results keep input order.

    anyio 版的 ``asyncio.gather``。与 gather 不同的是任一调用失败时其余调用会被
    取消，并按 anyio task group 的约定以 ``ExceptionGroup`` 抛出。
    """
    items = list(items)
    results: dict[int, R] = {}

    async def run(index: int, item: T) -> None:
        results[index] = await func(item)

    async with anyio.create_task_group() as tg:
        for index, item in enumerate(items):
            tg.start_soon(run, index, item)

    return [results[index] for index in range(len(items))]
