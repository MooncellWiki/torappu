from types import TracebackType
from contextvars import ContextVar
from typing import Any, TypeVar, cast
from collections.abc import Generator, AsyncGenerator
from contextlib import contextmanager, asynccontextmanager

import httpx

from torappu.config import Config

from .response import Response
from .exception import RequestError, RequestFailed, RequestTimeout
from .typing import (
    URLTypes,
    CookieTypes,
    HeaderTypes,
    ContentTypes,
    RequestFiles,
    QueryParamTypes,
)

T = TypeVar("T")


class WikiCore:
    def __init__(self, api_url: str, config: Config):
        self.config = config or Config()
        self.api_url = api_url
        self.cookies: CookieTypes | None = None
        self.__sync_client: ContextVar[httpx.Client | None] = ContextVar(
            "sync_client", default=None
        )
        self.__async_client: ContextVar[httpx.AsyncClient | None] = ContextVar(
            "async_client", default=None
        )

    # sync context
    def __enter__(self):
        if self.__sync_client.get() is not None:
            raise RuntimeError("Cannot enter sync context twice")
        self.__sync_client.set(self._create_sync_client())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ):
        cast(httpx.Client, self.__sync_client.get()).close()
        self.__sync_client.set(None)

    # async context
    async def __aenter__(self):
        if self.__async_client.get() is not None:
            raise RuntimeError("Cannot enter async context twice")
        self.__async_client.set(self._create_async_client())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ):
        await cast(httpx.AsyncClient, self.__async_client.get()).aclose()
        self.__async_client.set(None)

    # default args for creating client
    def _get_client_defaults(self):
        return {
            "cookies": self.cookies,
            "timeout": self.config.timeout,
            "follow_redirects": True,
        }

    # create sync client
    def _create_sync_client(self) -> httpx.Client:
        return httpx.Client(**self._get_client_defaults())

    # get or create sync client
    @contextmanager
    def get_sync_client(self) -> Generator[httpx.Client, None, None]:
        if client := self.__sync_client.get():
            yield client
        else:
            client = self._create_sync_client()
            try:
                yield client
            finally:
                client.close()

    # create async client
    def _create_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**self._get_client_defaults())

    # get or create async client
    @asynccontextmanager
    async def get_async_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        if client := self.__async_client.get():
            yield client
        else:
            client = self._create_async_client()
            try:
                yield client
            finally:
                await client.aclose()

    # sync request
    def _request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
    ) -> httpx.Response:
        with self.get_sync_client() as client:
            try:
                return client.request(
                    method,
                    url,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    json=json,
                    headers=headers,
                    cookies=cookies,
                )
            except httpx.TimeoutException as e:
                raise RequestTimeout(e.request) from e
            except Exception as e:
                raise RequestError(repr(e)) from e

    # async request
    async def _arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
    ) -> httpx.Response:
        async with self.get_async_client() as client:
            try:
                return await client.request(
                    method,
                    url,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    json=json,
                    headers=headers,
                    cookies=cookies,
                )
            except httpx.TimeoutException as e:
                raise RequestTimeout(e.request) from e
            except Exception as e:
                raise RequestError(repr(e)) from e

    # check and parse response
    def _check(
        self,
        response: httpx.Response,
        response_model: type[T] = Any,
        error_models: dict[str, type] | None = None,
    ) -> Response[T]:
        if response.is_error:
            error_models = error_models or {}
            status_code = str(response.status_code)
            error_model = error_models.get(
                status_code,
                error_models.get(
                    f"{status_code[:-2]}XX", error_models.get("default", Any)
                ),
            )
            rep = Response(response, error_model)
            raise RequestFailed(rep)
        return Response(response, response_model)

    # sync request and check
    def request(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        response_model: type[T] = Any,
        error_models: dict[str, type] | None = None,
    ) -> Response[T]:
        raw_resp = self._request(
            method,
            url,
            params=params,
            content=content,
            data=data,
            files=files,
            json=json,
            headers=headers,
            cookies=cookies,
        )
        self.cookies = raw_resp.cookies
        return self._check(raw_resp, response_model, error_models)

    # async request and check
    async def arequest(
        self,
        method: str,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        content: ContentTypes | None = None,
        data: dict | None = None,
        files: RequestFiles | None = None,
        json: Any | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        response_model: type[T] = Any,
        error_models: dict[str, type] | None = None,
    ) -> Response[T]:
        raw_resp = await self._arequest(
            method,
            url,
            params=params,
            content=content,
            data=data,
            files=files,
            json=json,
            headers=headers,
            cookies=cookies,
        )
        self.cookies = raw_resp.cookies
        return self._check(raw_resp, response_model, error_models)
