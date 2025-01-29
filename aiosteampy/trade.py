import json
from datetime import datetime
from json import dumps as jdumps
from typing import TYPE_CHECKING, overload, Literal, Type, TypeAlias, Callable

from yarl import URL

from .constants import STEAM_URL, CORO
from .exceptions import ApiError, SteamForbiddenError
from .models import (
    TradeOffer,
    TradeOfferItem,
    TradeOfferStatus,
    HistoryTradeOffer,
    HistoryTradeOfferItem,
    EconItemType,
)
from .typed import TradeOffersSummary
from .utils import create_ident_code, to_int_boolean, steam_id_to_account_id, account_id_to_steam_id
from ..steampy.utils import texts_between

if TYPE_CHECKING:
    from .client import SteamCommunityMixin

__all__ = ("TradeMixin",)

TRADE_OFFERS: TypeAlias = tuple[list[TradeOffer], list[TradeOffer]]


class TradeMixin:
    """
    Mixin with trade offers related methods.
    Depends on :class:`aiosteampy.confirmation.ConfirmationMixin`,
    :class:`aiosteampy.public.SteamPublicMixin`.
    """

    __slots__ = ()

    async def remove_trade_offer(self, offer_id: int, offer: TradeOffer | None):
        """
        Remove trade offer silently from cache.

        You can override this method to provide your custom storage.
        """

    async def store_trade_offer(self, offer_id: int, offer: TradeOffer):
        """
        Cache trade offer to inner store.

        You can override this method to provide your custom storage.
        """

    async def store_multiple_trade_offers(self, offer_ids: list[int], offers: list[TradeOffer]):
        """
        Cache multiple trade offers to inner store.

        You can override this method to provide your custom storage.
        """

        for index, offer_id in enumerate(offer_ids):
            await self.store_trade_offer(offer_id, offers[index])

    async def get_trade_offer(self, offer_id: int) -> TradeOffer | None:
        """
        Get trade offer from storage.

        You can override this method to provide your custom storage.
        """

    async def get_trade_offers(self, predicate: Callable[[TradeOffer], bool] = None) -> list[TradeOffer]:
        """
        Cached trade offers.

        You can override this method to provide your custom storage.
        """

    async def get_or_fetch_trade_offer(self, offer_id: int) -> TradeOffer:
        """
        Get specific trade from cache. Fetch it and store, if there is no one.

        :raises ApiError: if there is error when trying to fetch `TradeOffer`
        """

        trade = await self.get_trade_offer(offer_id)
        if not trade:
            trade = await self.fetch_trade(offer_id)

        return trade

    async def fetch_trade(self: "SteamCommunityMixin", offer_id: int):
        # -> TradeOffer:
        """
        Fetch trade offer from Steam.

        :raises ApiError:
        """

        params = {
            "access_token": self._access_token,
            "tradeofferid": offer_id,
            "language": self.language,
            "get_descriptions": 0,  # 1 TO GET DESCRIPTIONS
        }
        r = await self.session.get(STEAM_URL.API.IEconService.GetTradeOffer, params=params)
        rj: dict = await r.json()
        if not rj.get("response"):
            raise ApiError(f"Can't fetch trade offer [{offer_id}].", rj)

        data: dict[str, dict | list[dict]] = rj["response"]
        item_descrc_map = {}
        # self._update_item_descrs_map_for_trades(data["descriptions"], item_descrc_map)

        # trade = self._create_trade_offer(data["offer"], item_descrc_map)
        # await self.store_trade_offer(trade.id, trade)
        return data['offer']

    @classmethod
    def _update_item_descrs_map_for_trades(
            cls: Type["SteamCommunityMixin"],
            data: list[dict],
            item_descrs_map: dict[str, dict],
    ):
        for desc in data:
            key = create_ident_code(desc["classid"], desc["appid"])
            if key not in item_descrs_map:
                item_descrs_map[key] = cls._create_item_description_kwargs(desc, [desc])

    def _create_trade_offer(
            self: "SteamCommunityMixin",
            data: dict,
            item_descrs_map: dict[str, dict],
    ) -> TradeOffer:
        return TradeOffer(
            id=int(data["tradeofferid"]),
            owner_id=self.steam_id,
            partner_id=data["accountid_other"],
            is_our_offer=data["is_our_offer"],
            expiration_time=datetime.fromtimestamp(data["expiration_time"]),
            time_created=datetime.fromtimestamp(data["time_created"]),
            time_updated=datetime.fromtimestamp(data["time_updated"]),
            items_to_give=self._parse_items_for_trade(data.get("items_to_give", ()), item_descrs_map),
            items_to_receive=self._parse_items_for_trade(data.get("items_to_receive", ()), item_descrs_map),
            message=data["message"],
            status=TradeOfferStatus(data["trade_offer_state"]),
        )

    @classmethod
    def _parse_items_for_trade(
            cls,
            items: list[dict],
            item_descrs_map: dict[str, dict],
    ) -> list[TradeOfferItem]:
        return [
            TradeOfferItem(
                asset_id=a_data["assetid"],
                amount=int(a_data["amount"]),
                missing=a_data["missing"],
                est_usd=int(a_data["est_usd"]),
                **item_descrs_map[create_ident_code(a_data["classid"], a_data["appid"])],
            )
            for a_data in items
        ]

    @overload
    async def fetch_trade_offers(
            self,
            *,
            time_historical_cutoff: int = ...,
            sent: bool = ...,
            received: bool = ...,
    ) -> TRADE_OFFERS:
        ...

    @overload
    async def fetch_trade_offers(
            self,
            *,
            active_only: Literal[False],
            historical_only: Literal[True],
            sent: bool = ...,
            received: bool = ...,
    ) -> TRADE_OFFERS:
        ...

    async def fetch_trade_offers(
            self: "SteamCommunityMixin",
            *,
            active_only=True,
            time_historical_cutoff: int = None,
            historical_only=False,
            sent=True,
            received=True,
            **kwargs,
    ):
        # -> TRADE_OFFERS:
        """
        Fetch trade offers from Steam Web Api.

        :param active_only: fetch active, changed since `time_historical_cutoff` tradeoffs only or not
        :param time_historical_cutoff: timestamp for `active_only`
        :param historical_only: opposite for `active_only`
        :param sent: include sent offers or not
        :param received: include received offers or not
        :return: sent trades, received trades lists
        """

        params = {
            "access_token": self._access_token,
            "active_only": to_int_boolean(active_only),
            "get_sent_offers": to_int_boolean(sent),
            "get_received_offers": to_int_boolean(received),
            "historical_only": to_int_boolean(historical_only),
            "get_descriptions": 1,
            "cursor": 0,
            "language": self.language,
            **kwargs,
        }
        if active_only and time_historical_cutoff is not None:
            params["time_historical_cutoff"] = time_historical_cutoff

        item_descrs_map = {}
        offer_sent_datas = []
        offer_received_datas = []

        while True:
            r = await self.session.get(STEAM_URL.API.IEconService.GetTradeOffers, params=params)
            rj = await r.json()
            if not rj.get("response"):
                raise ApiError(f"Can't fetch trade offers.", rj)

            data: dict[str, dict | list[dict]] = rj["response"]
            offer_sent_datas.extend(data.get("trade_offers_sent", ()))
            offer_received_datas.extend(data.get("trade_offers_received", ()))
            # self._update_item_descrs_map_for_trades(data["descriptions"], item_descrs_map)

            params["cursor"] = data.get("next_cursor", 0)
            if not params["cursor"]:
                break

        # o_sent = [self._create_trade_offer(d, item_descrs_map) for d in offer_sent_datas]
        # o_received = [self._create_trade_offer(d, item_descrs_map) for d in offer_received_datas]
        #
        # await self.store_multiple_trade_offers(
        #     [*(t.id for t in o_sent), *(t.id for t in o_received)],
        #     [*o_sent, *o_received],
        # )

        return {
            "sent": offer_sent_datas,
            "received": offer_received_datas,
        }

    async def get_trade_offers_summary(self: "SteamCommunityMixin") -> TradeOffersSummary:
        r = await self.session.get(STEAM_URL.API.IEconService.GetTradeOffersSummary, params={"key": self._api_key})
        rj: dict[str, TradeOffersSummary] = await r.json()
        if not rj.get("response"):
            raise ApiError(f"Can't fetch trade offers summary.", rj)

        return rj["response"]

    async def get_trade_receipt(self: "SteamCommunityMixin", offer_id: int, **kwargs) -> HistoryTradeOffer:
        """Fetch single trade offer from history."""

        params = {
            "access_token": self._access_token,
            "tradeid": offer_id,
            "get_descriptions": 1,
            "language": self.language,
            **kwargs,
        }
        r = await self.session.get(STEAM_URL.API.IEconService.GetTradeStatus, params=params)
        rj = await r.json()
        if not rj.get("response"):
            raise ApiError(f"Can't fetch trade status.", rj)

        item_descrs_map = {}
        self._update_item_descrs_map_for_trades(rj["response"]["descriptions"], item_descrs_map)

        return self._create_history_trade_offer(rj["response"]["trades"][0], item_descrs_map)

    async def get_trade_receipt_html(self: "SteamCommunityMixin", trade_id: int):
        r = await  self.session.get(f'https://steamcommunity.com/trade/{trade_id}/receipt')
        html = await r.text()
        items = [json.loads(item) for item in texts_between(html, 'oItem = ', ';\n\toItem.appid')]
        return items

    async def get_trade_history(
            self: "SteamCommunityMixin",
            max_trades=100,
            *,
            start_after_time=0,
            start_after_trade_id=0,
            navigating_back=False,
            include_failed=True,
            **kwargs,
    ) -> tuple[list[HistoryTradeOffer], int]:
        """
        Fetch history trades with changed assets data.
        You can paginate by yourself with this method.

        :param max_trades: page size
        :param start_after_time: timestamp
        :param start_after_trade_id:
        :param navigating_back:
        :param include_failed:
        :return: list of `HistoryTradeOffer`, total trades count
        """

        params = {
            "key": self._api_key,
            "max_trades": max_trades,
            "get_descriptions": 1,
            "include_total": 1,
            "include_failed": to_int_boolean(include_failed),
            "navigating_back": to_int_boolean(navigating_back),
            "start_after_time": start_after_time,
            "start_after_tradeid": start_after_trade_id,
            "language": self.language,
            **kwargs,
        }
        r = await self.session.get(STEAM_URL.API.IEconService.GetTradeHistory, params=params)
        rj = await r.json()
        if not rj.get("response"):
            raise ApiError(f"Can't fetch trades history.", rj)

        item_descrs_map = {}
        data: dict[str, int | bool | dict | list[dict]] = rj["response"]
        self._update_item_descrs_map_for_trades(data["descriptions"], item_descrs_map)

        return (
            [self._create_history_trade_offer(d, item_descrs_map) for d in data["trades"]],
            data["total_trades"],
        )

    def _create_history_trade_offer(
            self: "SteamCommunityMixin",
            data: dict,
            item_descrs_map: dict[str, dict],
    ) -> HistoryTradeOffer:
        return HistoryTradeOffer(
            id=int(data["tradeid"]),
            owner_id=self.steam_id,
            partner_id=steam_id_to_account_id(int(data["steamid_other"])),
            time_init=datetime.fromtimestamp(data["time_init"]),
            status=TradeOfferStatus(data["status"]),
            assets_given=self._parse_items_for_history_trades(data.get("assets_given", ()), item_descrs_map),
            assets_received=self._parse_items_for_history_trades(data.get("assets_received", ()), item_descrs_map),
        )

    @classmethod
    def _parse_items_for_history_trades(
            cls,
            items: list[dict],
            item_descrs_map: dict[str, dict],
    ) -> list[HistoryTradeOfferItem]:
        return [
            HistoryTradeOfferItem(
                asset_id=int(a_data["assetid"]),
                amount=int(a_data["amount"]),
                new_asset_id=int(a_data["new_assetid"]),
                new_context_id=int(a_data["new_contextid"]),
                **item_descrs_map[create_ident_code(a_data["classid"], a_data["appid"])],
            )
            for a_data in items
        ]

    async def _do_action_with_offer(
            self: "SteamCommunityMixin",
            offer_id: int,
            action: Literal["cancel", "decline"],
    ):
        r = await self.session.post(STEAM_URL.TRADE / f"{offer_id}/{action}", data={"sessionid": self.session_id})
        rj: dict[str, str] = await r.json()
        # return int(rj.get("tradeofferid", 0))
        return rj

    async def cancel_trade_offer(self: "SteamCommunityMixin", offer: int | TradeOffer):
        """Cancel outgoing trade offer. Remove offer from cache."""
        offer_id = offer
        # if isinstance(offer, TradeOffer):
        #     if not offer.is_our_offer:
        #         raise ValueError("You can't cancel not your offer! Are you trying to decline incoming offer?")
        #     offer_id = offer.id
        #     to_remove = offer
        # else:
        #     offer_id = offer
        #     to_remove = None
        return await self._do_action_with_offer(offer_id, "cancel")
        # if not resp_offer_id or resp_offer_id != offer_id:
        #     raise ApiError(f"Error while try to cancel offer [{offer_id}].")
        # return resp_offer_id
        # await self.remove_trade_offer(offer_id, to_remove)  # remove after making sure that all is okay

    async def decline_trade_offer(self: "SteamCommunityMixin", offer: int | TradeOffer):
        """Decline incoming trade offer. Remove offer from cache."""

        if isinstance(offer, TradeOffer):
            if offer.is_our_offer:
                raise ValueError("You can't decline your offer! Are you trying to cancel outgoing offer?")
            offer_id = offer.id
            to_remove = offer
        else:
            offer_id = offer
            to_remove = None
        resp_offer_id = await self._do_action_with_offer(offer_id, "decline")
        if not resp_offer_id or resp_offer_id != offer_id:
            raise ApiError(f"Error while try to decline offer [{offer_id}].")

        await self.remove_trade_offer(offer_id, to_remove)  # remove after making sure that all is okay

    @overload
    async def accept_trade_offer(self, offer: TradeOffer):
        ...

    @overload
    async def accept_trade_offer(self, offer: int, partner: int = ...):
        ...

    async def accept_trade_offer(self: "SteamCommunityMixin", offer: int | TradeOffer, partner: int = None):
        """
        Accept trade offer, yes. Remove offer from cache.

        .. note::
            Auto confirm accepting if needed.

            If you not pass `partner` but pass `trade offer id` -
            fetches :class:`aiosteampy.models.TradeOffer` from `Steam`.

        :param offer: `TradeOffer` or trade offer id
        :param partner: partner account id (id32) or steam id (id64)
        :raises ConfirmationError: if confirmation can't be found or while do action with
        :raises ApiError: if there is error when trying to fetch `TradeOffer`
        """
        offer_id = offer
        # if isinstance(offer, TradeOffer):
        #     if offer.is_our_offer:
        #         raise ValueError("You can't accept your offer! Are you trying to cancel outgoing offer?")
        #     offer_id = offer.id
        #     partner = offer.partner_id64
        #     to_remove = TradeOffer
        # else:  # int
        #     if not partner:
        #         fetched = await self.get_or_fetch_trade_offer(offer)
        #         return await self.accept_trade_offer(fetched)
        #
        #     offer_id = offer
        #     partner = account_id_to_steam_id(partner) if partner < 4294967296 else partner  # 2**32
        #     to_remove = None

        data = {
            "sessionid": self.session_id,
            "tradeofferid": offer_id,
            "serverid": 1,
            "partner": partner,
            "captcha": "",
        }
        url_base = STEAM_URL.TRADE / str(offer_id)
        r = await self.session.post(url_base / "accept", data=data, headers={"Referer": str(url_base)})
        rj: dict = await r.json()
        if rj is None:
            if r.status == 403:
                raise SteamForbiddenError(f"Forbidden to accept trade offer {offer_id}.")
            raise ApiError(f"Can't accept trade offer request {data}  status {r.status} resp {await r.text()}.")
        if rj.get("needs_mobile_confirmation"):
            await self.confirm_trade_offer(offer_id)

        return rj
        # await self.remove_trade_offer(offer_id, to_remove)

    @overload
    async def make_trade_offer(
            self,
            obj: int,
            to_give: list[EconItemType] = ...,
            to_receive: list[EconItemType] = ...,
            message: str = ...,
            *,
            token: str = ...,
            confirm: bool = ...,
            countered_id: int = ...,
    ) -> int:
        ...

    @overload
    async def make_trade_offer(
            self,
            obj: str,
            to_give: list[EconItemType] = ...,
            to_receive: list[EconItemType] = ...,
            message: str = ...,
            *,
            confirm: bool = ...,
            countered_id: int = ...,
    ) -> int:
        ...

    async def make_trade_offer(
            self: "SteamCommunityMixin",
            obj: int | str,
            to_give: list[EconItemType] = (),
            to_receive: list[EconItemType] = (),
            message="",
            *,
            token: str = None,
            confirm=True,
            countered_id: int = None,
            **kwargs,
    ) -> int:
        """
        Make (send) steam trade offer to partner.

        .. note:: Make sure that partner is in friends list if you not pass trade url or trade token.

        :param obj: partner trade url, partner id(id32 or id64)
        :param token:
        :param to_give:
        :param to_receive:
        :param message:
        :param confirm:
        :param countered_id:
        :param kwargs:
        :return: trade offer id
        :raises ValueError: trade is empty
        """

        if not to_give and not to_receive:
            raise ValueError("You can't make empty trade offer!")

        trade_url, partner_id32, partner_id64, token = self._parse_make_offer_args(obj, token)
        base_url = STEAM_URL.TRADE / "new/"
        referer = trade_url or base_url % {"partner": partner_id32}
        offer_params = {}
        if token:
            referer %= {"token": token}
            offer_params["trade_offer_access_token"] = token
        data = {
            "sessionid": self.session_id,
            "serverid": 1,
            "partner": partner_id64,
            "tradeoffermessage": message,
            "json_tradeoffer": jdumps(
                {
                    "newversion": True,
                    "version": len(to_give) + len(to_receive) + 1,
                    "me": {"assets": [self._to_asset_dict(i) for i in to_give], "currency": [], "ready": False},
                    "them": {"assets": [self._to_asset_dict(i) for i in to_receive], "currency": [], "ready": False},
                }
            ),
            "captcha": "",
            "trade_offer_create_params": jdumps(offer_params),
            **kwargs,
        }
        if countered_id:
            data["tradeofferid_countered"] = countered_id

        headers = {"Referer": str(referer)}
        r = await self.session.post(base_url / "send", data=data, headers=headers)
        rj = await r.json()
        if r.status == 403:
            raise SteamForbiddenError(f"Forbidden to make trade offer to {partner_id64}.")
        if r.status!= 200 or not rj.get("tradeofferid"):
            raise ApiError(f"Can't make trade offer to status {r.status} {rj}.")
        offer_id = int(rj["tradeofferid"])
        if confirm and rj.get("needs_mobile_confirmation"):
            offer_id = await self.confirm_trade_offer(offer_id)

        return offer_id

    @staticmethod
    def _to_asset_dict(obj: EconItemType) -> dict[str, int | str]:
        return {"appid": obj[0], "contextid": str(obj[1]), "amount": obj[2], "assetid": str(obj[3])}

    @staticmethod
    def _parse_make_offer_args(obj: str | int, token: str | None) -> tuple[str | None, int, int, str | None]:
        trade_url = None
        if isinstance(obj, str):  # trade url
            trade_url = URL(obj)
            partner_id32 = int(trade_url.query["partner"])
            partner_id64 = account_id_to_steam_id(partner_id32)
            token = trade_url.query["token"]
            trade_url = str(trade_url)
        else:
            partner_id = obj
            if partner_id < 4294967296:  # 32
                partner_id32 = partner_id
                partner_id64 = account_id_to_steam_id(partner_id)
            else:  # 64
                partner_id64 = partner_id
                partner_id32 = steam_id_to_account_id(partner_id64)

        return trade_url, partner_id32, partner_id64, token

    @overload
    async def counter_trade_offer(
            self,
            obj: TradeOffer,
            to_give: list[EconItemType] = (),
            to_receive: list[EconItemType] = (),
            message="",
            *,
            confirm: bool = ...,
    ) -> int:
        ...

    @overload
    async def counter_trade_offer(
            self,
            obj: int,
            to_give: list[EconItemType] = (),
            to_receive: list[EconItemType] = (),
            message="",
            *,
            partner_id: int,
            confirm: bool = ...,
    ) -> int:
        ...

    def counter_trade_offer(
            self,
            obj: TradeOffer | int,
            to_give: list[EconItemType] = (),
            to_receive: list[EconItemType] = (),
            message="",
            *,
            partner_id: int = None,
            confirm=True,
            **kwargs,
    ) -> CORO[int]:
        """
        Counter trade offer with another.

        :param obj: `TradeOffer` or trade offer id of which you want to counter
        :param to_give:
        :param to_receive:
        :param message:
        :param partner_id:
        :param confirm:
        :return:
        """

        if isinstance(obj, TradeOffer):
            offer_id = obj.id
            to_give_updated = [*obj.items_to_give, *to_give]
            to_receive_updated = [*obj.items_to_receive, *to_receive]
            if obj.is_our_offer:
                raise ValueError("You can't counter yours offer!")
        else:  # trade id
            offer_id = obj
            to_give_updated = to_give
            to_receive_updated = to_receive

        return self.make_trade_offer(
            partner_id,
            to_give_updated,
            to_receive_updated,
            message,
            confirm=confirm,
            countered_id=offer_id,
            **kwargs,
        )
