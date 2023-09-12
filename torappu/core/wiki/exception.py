from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .response import Response


class WikiException(Exception):
    ...


class AuthCredentialError(WikiException):
    """Auth Credential Error"""


class AuthExpiredError(WikiException):
    """Auth Expired Error"""


class RequestError(WikiException):
    """Simple API request failed with unknown error"""


class RequestTimeout(WikiException):
    """Simple API request timeout"""

    def __init__(self, request: httpx.Request):
        self.request = request

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(method={self.request.method}, "
            f"url={self.request.url})"
        )


class RequestFailed(WikiException):
    """Simple API request failed with error status code"""

    def __init__(self, response: "Response"):
        self.request = response.raw_request
        self.response = response

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(method={self.request.method}, "
            f"url={self.request.url}, status_code={self.response.status_code})"
        )
