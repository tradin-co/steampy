from aiohttp import ClientResponseError

from steampy.aiosteampy import STEAM_URL, ApiError
from steampy.aiosteampy.client_v2 import SteamCommunityMixinV2
from steampy.aiosteampy.login import LoginMixin, REFERER_HEADER
from steampy.aiosteampy.utils_v2 import MailMessageProcessor


class LoginMixinV2(LoginMixin):

    def __init__(self, steam_guard_code_provider: MailMessageProcessor, *args, **kwargs):
        self._steam_guard_code_provider = steam_guard_code_provider

        super().__init__(*args, **kwargs)

    async def _update_auth_session_with_steam_guard_code(self: "SteamCommunityMixinV2", session_data: dict):
        # Doesn't check allowed confirmations, but it's probably not needed
        # as steam accounts suited for trading must have a steam guard and device code.

        # https://github.com/DoctorMcKay/node-steam-session/blob/64463d7468c1c860afb80164b8c5831e629f657f/src/LoginSession.ts#L735
        # https://github.com/DoctorMcKay/node-steam-session/blob/64463d7468c1c860afb80164b8c5831e629f657f/src/enums-steam/EAuthSessionGuardType.ts
        self.steam_id = int(session_data["response"]["steamid"])

        data = {
            "client_id": session_data["response"]["client_id"],
            "steamid": session_data["response"]["steamid"],
            "code_type": 2,
            "code": await self._steam_guard_code_provider.get_last_mail_message_code(),
        }

        try:
            await self.session.post(
                STEAM_URL.API.IAuthService.UpdateAuthSessionWithSteamGuardCode,
                data=data,
                headers=REFERER_HEADER,
            )
        except ClientResponseError:
            raise ApiError("Error updating steam guard code")