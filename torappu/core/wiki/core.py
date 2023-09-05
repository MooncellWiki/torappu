import json
from urllib.parse import quote
from types import TracebackType
from contextvars import ContextVar
from typing import Any, TypeVar, cast
from collections.abc import Generator, AsyncGenerator
from contextlib import contextmanager, asynccontextmanager

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt

from torappu.config import Config
from torappu.core.wiki.typing import (
    URLTypes,
    CookieTypes,
    HeaderTypes,
    ContentTypes,
    RequestFiles,
    QueryParamTypes,
)

from .response import Response
from .exception import RequestError, RequestFailed, RequestTimeout

T = TypeVar("T")


class Wiki:
    def __init__(self, api_url: str, config: Config):
        self.config = config or Config()
        self.api_url = api_url
        self.mode = self.config.environment
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

    async def login(
        self,
        username,
        password,
    ):
        async with self.get_async_client() as client:
            lgtoken = await client.get(
                self.api_url,
                params={
                    "format": "json",
                    "action": "query",
                    "meta": "tokens",
                    "type": "login",
                },
            )
            res = await client.post(
                self.api_url,
                data={
                    "format": "json",
                    "action": "login",
                    "lgname": username,
                    "lgpassword": password,
                    "lgtoken": lgtoken.json()["query"]["tokens"]["logintoken"],
                },
            )
            if res.json()["login"]["result"] != "Success":
                raise RuntimeError(res.json()["login"]["reason"])

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
        return self._check(raw_resp, response_model, error_models)

    @retry(stop=stop_after_attempt(3))
    async def edit(
        self,
        title=None,
        pageid=None,
        section=None,
        sectiontitle=None,
        text=None,
        summary=None,
        minor=None,
        bot=True,
        createonly=None,
        nocreate=None,
        prependtext=None,
        appendtext=None,
        redirect=None,
        contentformat=None,
        contentmodel=None,
    ):
        """
        :param title: 要编辑的页面标题。不能与pageid一起使用。
        :param pageid:要编辑的页面的页面 ID。不能与title一起使用。
        :param section:段落数。0用于首段，new用于新的段落。NOTICE:会覆盖==xx==的部分
        :param sectiontitle:新段落的标题。
        :param text:页面内容。
        :param summary:编辑摘要。当section=new且未设置sectiontitle时，还包括小节标题。
        :param minor:小编辑。
        :param bot:机器人编辑。
        :param createonly:不要编辑页面，如果已经存在。
        :param nocreate:如果该页面不存在，则抛出一个错误。
        :param prependtext:将该文本添加到该页面的开始。覆盖text。
        :param appendtext:将该文本添加到该页面的结尾。覆盖text。
        :param redirect:自动解决重定向。
        :param contentformat:
        用于输入文本的内容序列化格式。application/json、text/plain、text/css、text/x-wiki、text/javascript
        :param contentmodel:
        新内容的内容模型。GadgetDefinition、Scribunto、sanitized-css、flow-board、wikitext、javascript、json、css、text、smw/schema
        :type minor: bool
        :type bot: bool
        :type createonly:bool
        :type nocreate:bool
        :type redirect:bool
        :return:post response
        """
        args = locals().copy()
        args.pop("self")
        if self.mode != "product":
            logger.info(args)
            return
        boolargs = {"minor", "createonly", "nocreate", "redirect", "bot"}
        async with self.get_async_client() as client:
            token = await client.get(
                self.api_url,
                params={
                    "format": "json",
                    "action": "query",
                    "meta": "tokens",
                },
            )
            post_data = {
                "format": "json",
                "action": "edit",
                "token": token.json()["query"]["tokens"]["csrftoken"],
            }
            for key in args:
                if args[key] is not None:
                    if key in boolargs and args[key]:
                        post_data[key] = "1"
                    else:
                        post_data[key] = args[key]
            # time.sleep(1)
            return await client.post(self.api_url, data=post_data)

    @retry(stop=stop_after_attempt(3))
    async def read(self, title):
        """
        :param title: 名称空间:页面名
        :return: wikitext
        """
        async with self.get_async_client() as client:
            res = await client.post(
                self.api_url,
                data={
                    "format": "json",
                    "action": "query",
                    "titles": title,
                    "prop": "revisions",
                    "rvprop": "content",
                },
            )
            ret = json.loads(res.text)["query"]["pages"]
            for k in ret:
                ret = ret[k]
                break
            return ret["revisions"][0]["*"]

    @retry(stop=stop_after_attempt(3))
    async def category(self, category):
        async with self.get_async_client() as client:
            res = await client.post(
                self.api_url,
                data={
                    "format": "json",
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": category,
                    "cmlimit": 3000,
                },
            )
            ret = res.json()["query"]["categorymembers"]
            return [page["title"] for page in ret]

    @retry(stop=stop_after_attempt(3))
    async def protect(
        self, title=None, pageid=None, protections=None, reason=None, cascade=None
    ):
        """
        :param title:要（解除）保护的页面标题。不能与pageid一起使用。
        :param pageid:要（解除）保护的页面ID。不能与title一起使用。
        :param protections:
        保护等级列表，格式：action=level（例如edit=sysop）。等级all意味着任何人都可以执行操作，也就是说没有限制。
        注意：未列出的操作将移除限制。
        :param reason:（解除）保护的原因。
        :param cascade:
        启用连锁保护（也就是保护包含于此页面的页面）。如果所有提供的保护等级不支持连锁，就将其忽略。
        :type cascade:bool
        :return:
        """
        args = locals().copy()
        args.pop("self")
        if self.mode != "product":
            logger.info(args)
            return
        async with self.get_async_client() as client:
            token = await client.get(
                self.api_url,
                params={
                    "format": "json",
                    "action": "query",
                    "meta": "tokens",
                },
            )
            post_data = {
                "format": "json",
                "action": "protect",
                "token": token.json()["query"]["tokens"]["csrftoken"],
                "expiry": "infinite",
            }
            for key in args:
                if args[key] is not None:
                    if key == "cascade" and args[key]:
                        post_data[key] = "1"
                    else:
                        post_data[key] = args[key]
            return await client.post(self.api_url, data=post_data)

    @retry(stop=stop_after_attempt(3))
    async def upload(self, filepath, filename, comment=None, text=None):
        """
        :param filepath:文件路径
        :param filename:目标文件名
        :param comment:上传注释。如果没有指定text，那么它也被用于新文件的初始页面文本。
        :param text:用于新文件的初始页面文本。
        :return:
        """
        args = locals().copy()
        args.pop("self")

        async with self.get_async_client() as client:
            token = await client.get(
                self.api_url,
                params={
                    "format": "json",
                    "action": "query",
                    "meta": "tokens",
                },
            )
            upload_data = {
                "format": "json",
                "action": "upload",
                "filename": filename,
                "ignorewarnings": "1",
                "token": token.json()["query"]["tokens"]["csrftoken"],
            }
            header = {
                "Content-Disposition": 'form-data; name="data"; filename="%s"'
                % quote(filename)
            }
            for key in args:
                if args[key] is not None:
                    upload_data[key] = args[key]
            r = await client.post(
                self.api_url,
                data=upload_data,
                files={"file": (quote(filename), open(filepath, "rb"))},
                headers=header,
            )
            return r
