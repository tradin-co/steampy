from steampy.aiosteampy import STEAM_URL, ApiError
from steampy.aiosteampy.client import SteamCommunityMixin
from steampy.aiosteampy.login_v2 import LoginMixinV2
from steampy.aiosteampy.utils_v2 import TimeAligner


class SteamCommunityMixinV2(LoginMixinV2, SteamCommunityMixin):

    async def link_steam_guard(self):
        mafile_data = await self._add_authenticator()
        self._shared_secret = mafile_data.get('shared_secret')
        result = await self._finalize_link_steam_guard()
        if not result.get('success'):
            raise ApiError("Error get confirmation for finalize add two factor authenticator")
        else:
            return mafile_data

    async def _add_authenticator(self):
        url = f"{STEAM_URL.API.ITwoFactorService.AddAuthenticator}/?access_token={self._access_token}"
        data = {
            "steamid": str(self.steam_id),
            "authenticator_type": "1",
            "device_identifier": self.device_id,
            "sms_phone_id": "2"
        }
        r = await self.session.post(
            url,
            data=data,
        )
        result = await r.json()
        return result

    async def _finalize_link_steam_guard(self):
        url = f"{STEAM_URL.API.ITwoFactorService.FinalizeAddAuthenticator}/?access_token={self._access_token}"
        data = {
            "steamid": str(self.steam_id),
            "authenticator_time": await TimeAligner.get_steam_time_async(),
            "authenticator_code": self.two_factor_code,
            "authenticator_type": "1",
            "activation_code": await self._steam_guard_code_provider.get_last_mail_message_code(),
        }
        r = await self.session.post(
            url,
            data=data,
        )
        result = await r.json()
        return result


class SteamClientV2(SteamCommunityMixinV2):
    """Ready to use client class with all inherited methods."""

    __slots__ = (
        "_is_logged",
        "_refresh_token",
        "_access_token",
        "session",
        "username",
        "steam_id",
        "_password",
        "_shared_secret",
        "_identity_secret",
        "_api_key",
        "trade_token",
        "device_id",
        "_wallet_currency",
        "_wallet_country",
    )
