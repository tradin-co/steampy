from typing import TypeAlias

from steampy.aiosteampy.constants import EResult

_json_types: TypeAlias = dict | list | str | int


class _BaseExc(Exception):
    def __init__(self, msg=""):
        self.msg = msg

class SteamError(Exception):
    """All errors related to Steam"""

class EResultError(SteamError):
    """Raised when Steam response data contain `success` field with error code"""

    def __init__(self, msg: str, result: EResult, data=None):
        self.msg = msg
        self.result = result
        self.data = data


class ApiError(_BaseExc):
    """Raises when there is a problem with calling steam web/api methods (mostly due to `success` field),
    exclude response statuses."""

    def __init__(self, msg: str, resp: _json_types = None):
        super().__init__(msg)
        self.resp = resp

class SteamForbiddenError(_BaseExc):
    """When failed to access to some resource."""

    def __init__(self, msg: str, resp: _json_types = None):
        super().__init__(msg)
        self.resp = resp

class LoginError(ApiError):
    """When failed to do login."""


class ConfirmationError(_BaseExc):
    """Errors of all related to confirmation."""


class SessionExpired(Exception):
    """Raised when session is expired, and you need to do login."""
