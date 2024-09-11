"""
Helper functions to restore/load, dump SteamClient client and components,
decorators to check instance attributes.
"""
from http.cookies import SimpleCookie, Morsel
from typing import TYPE_CHECKING

from aiohttp import ClientSession

from .utils import JSONABLE_COOKIE_JAR, attribute_required

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

if TYPE_CHECKING:
    from .client import SteamClientBase

__all__ = (
    "restore_from_cookies",
    "currency_required",
    "identity_secret_required",
)


def update_session_cookies(session: ClientSession, cookies: JSONABLE_COOKIE_JAR):
    """Update the session cookies from jsonable cookie jar."""

    for cookie_data in cookies:
        c = SimpleCookie()
        for k, v in cookie_data.items():
            copied = dict(**v)  # copy to avoid modification of the arg
            m = Morsel()
            m._value = copied.pop("value")
            m._key = copied.pop("key")
            m._coded_value = copied.pop("coded_value")
            m.update(copied)
            c[k] = m

        session.cookie_jar.update_cookies(c)


async def restore_from_cookies(cookies: JSONABLE_COOKIE_JAR, client: "SteamClientBase") -> bool:
    """
    Helper func. Restore client session from cookies. Login if session is not alive.
    Return `True` if cookies are valid and not expired.
    """

    update_session_cookies(client.session, cookies)

    if not (await client.is_session_alive()):  # session initiated here
        await client.login(init_session=False)
        return False
    else:
        return True


# TODO restore from object/dict, dump to object/dict


currency_required = attribute_required(
    "currency",
    "You must provide a currency to client or init data before use this method",
)

identity_secret_required = attribute_required(
    "_identity_secret",
    "You must provide identity secret to client before use this method",
)
