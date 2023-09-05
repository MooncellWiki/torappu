from typing import IO, TypeVar

import httpx

T = TypeVar("T")

URLTypes = httpx.URL | str

PrimitiveData = str | int | float | bool | None
QueryParamTypes = (
    httpx.QueryParams
    | dict[str, PrimitiveData | list[PrimitiveData]]
    | list[tuple[str, PrimitiveData]]
    | tuple[tuple[str, PrimitiveData], ...]
    | str
    | bytes
)

HeaderTypes = (
    httpx.Headers
    | dict[str, str]
    | dict[bytes, bytes]
    | list[tuple[str, str]]
    | list[tuple[bytes, bytes]]
)

CookieTypes = httpx.Cookies | dict[str, str] | list[tuple[str, str]]

ContentTypes = str | bytes

FileContent = IO[bytes] | bytes
# file (or bytes)
# | (filename, file (or bytes))
# | (filename, file (or bytes), content_type)
FileTypes = (
    FileContent
    | tuple[str | None, FileContent]
    | tuple[str | None, FileContent, str | None]
)
RequestFiles = dict[str, FileTypes] | list[tuple[str, FileTypes]]
