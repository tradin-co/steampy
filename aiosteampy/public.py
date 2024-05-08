from typing import Callable, TypeAlias, overload, TYPE_CHECKING

from aiohttp import ClientResponseError
from yarl import URL

from .models import (
    ItemDescriptionEntry,
    ItemTag,
    ItemDescription,
    EconItem,
    ItemAction,
    MarketListing,
    MarketListingItem,
    ITEM_DESCR_TUPLE,
)
from .constants import STEAM_URL, Game, Currency, GameType, Language, T_KWARGS
from .typed import ItemOrdersHistogram, ItemOrdersActivity, PriceOverview
from .exceptions import ApiError
from .utils import create_ident_code

if TYPE_CHECKING:
    from .client import SteamPublicClient

__all__ = ("SteamPublicMixin", "INVENTORY_URL")

INV_PAGE_SIZE = 2000  # steam new limit rule
INVENTORY_URL = STEAM_URL.COMMUNITY / "inventory"
PREDICATE: TypeAlias = Callable[[EconItem], bool]
PRIVATE_USER_EXC_MSG = "User inventory is private."
ITEM_MARKET_LISTINGS_DATA: TypeAlias = tuple[list[MarketListing], int]


class SteamPublicMixin:
    """Contains methods that do not require authentication."""

    __slots__ = ()

    # init method with attr in client

    async def get_user_inventory(
        self: "SteamPublicClient",
        steam_id: int,
        game: GameType,
        *,
        predicate: PREDICATE = None,
        page_size=INV_PAGE_SIZE,
        **kwargs: T_KWARGS,
    ) -> list[EconItem]:
        """
        Fetches inventory of user.

        :param steam_id: steamid64 of user
        :param game: just Steam Game
        :param page_size: max items on page. Current Steam limit is 2000
        :param predicate: callable with single arg `EconItem`, must return bool
        :return: list of `EconItem`
        :raises ApiError: if response data `success` is False or user inventory is private
        """

        inv_url = INVENTORY_URL / f"{steam_id}/"
        params = {"l": self.language, "count": page_size, **kwargs}
        headers = {"Referer": str(inv_url)}
        url = inv_url / f"{game[0]}/{game[1]}"

        item_descrs_map = {}
        items = []
        more_items = True
        last_assetid = None
        while more_items:
            params_pag = {**params, "start_assetid": last_assetid} if last_assetid else params
            data = await self._fetch_inventory(url, params_pag, headers)
            more_items = data.get("more_items", False)
            if more_items:
                last_assetid = data.get("last_assetid")

            items.extend(self._parse_items(data, steam_id, item_descrs_map))

        return [i for i in items if predicate(i)] if predicate else items

    async def _fetch_inventory(
        self: "SteamPublicClient",
        url: URL,
        params: dict,
        headers: dict,
    ) -> dict[str, list[dict] | int]:
        try:
            r = await self.session.get(url, params=params, headers=headers)
        except ClientResponseError as e:
            raise ApiError(PRIVATE_USER_EXC_MSG, str(url)) if e.status == 403 else e

        rj: dict[str, list[dict] | int] = await r.json()
        if not rj.get("success"):
            raise ApiError(f"Can't fetch inventory.", rj)

        return rj

    @staticmethod
    def _find_game_for_asset(description_data: dict[str, int], assets: list[dict[str, int | str]]) -> GameType:
        try:
            return Game(description_data["appid"])
        except ValueError:
            for asset in assets:
                if asset["classid"] == description_data["classid"]:
                    return asset["appid"], int(asset["contextid"])

    @classmethod
    def _parse_items(
        cls,
        data: dict[str, list[dict]],
        steam_id: int,
        item_descrs_map: dict[str, dict],
    ) -> list[EconItem]:
        for d_data in data["descriptions"]:
            key = d_data["classid"]
            if key not in item_descrs_map:
                item_descrs_map[key] = cls._create_item_description_kwargs(d_data, data["assets"])

        return [
            EconItem(
                asset_id=int(asset_data["assetid"]),
                owner_id=steam_id,
                amount=int(asset_data["amount"]),
                **item_descrs_map[asset_data["classid"]],
            )
            for asset_data in data["assets"]
        ]

    @classmethod
    def _create_item_actions(cls, actions: list[dict]) -> tuple[ItemAction, ...]:
        return tuple(ItemAction(a_data["link"], a_data["name"]) for a_data in actions)

    @classmethod
    def _create_item_tags(cls, tags: list[dict]) -> tuple[ItemTag, ...]:
        return tuple(
            ItemTag(
                category=t_data["category"],
                internal_name=t_data["internal_name"],
                localized_category_name=t_data["localized_category_name"],
                localized_tag_name=t_data["localized_tag_name"],
                color=t_data.get("color"),
            )
            for t_data in tags
        )

    @classmethod
    def _create_item_description_entries(cls, descriptions: list[dict]) -> tuple[ItemDescriptionEntry, ...]:
        return tuple(
            ItemDescriptionEntry(
                value=de_data["value"],
                color=de_data.get("color"),
            )
            for de_data in descriptions
            if de_data["value"] != " "  # ha, surprise!
        )

    @classmethod
    def _create_item_description_kwargs(cls, data: dict, assets: list[dict[str, int | str]]) -> dict:
        return dict(
            class_id=int(data["classid"]),
            instance_id=int(data["instanceid"]),
            game=cls._find_game_for_asset(data, assets),
            name=data["name"],
            market_name=data["market_name"],
            market_hash_name=data["market_hash_name"],
            name_color=data["name_color"] or None,
            background_color=data.get("name_color") or None,
            type=data["type"] or None,
            icon=data["icon_url"],
            icon_large=data.get("icon_url_large"),
            commodity=bool(data["commodity"]),
            tradable=bool(data["tradable"]),
            marketable=bool(data["marketable"]),
            market_tradable_restriction=data.get("market_tradable_restriction"),
            market_buy_country_restriction=data.get("market_buy_country_restriction"),
            market_fee_app=data.get("market_fee_app"),
            market_marketable_restriction=data.get("market_marketable_restriction"),
            actions=cls._create_item_actions(data.get("actions", ())),
            market_actions=cls._create_item_actions(data.get("market_actions", ())),
            owner_actions=cls._create_item_actions(data.get("owner_actions", ())),
            tags=cls._create_item_tags(data.get("tags", ())),
            descriptions=cls._create_item_description_entries(data.get("descriptions", ())),
            owner_descriptions=cls._create_item_description_entries(data.get("owner_descriptions", ())),
            fraud_warnings=tuple(*data.get("fraudwarnings", ())),
        )

    async def fetch_item_orders_histogram(
        self: "SteamPublicClient",
        item_nameid: int,
        *,
        lang: Language = None,
        country: str = None,
        currency: Currency = None,
        **kwargs: T_KWARGS,
    ) -> ItemOrdersHistogram:
        """
        Do what described in method name.

        .. seealso::
            * https://github.com/Revadike/InternalSteamWebAPI/wiki/Get-Market-Item-Orders-Histogram
            * https://github.com/somespecialone/steam-item-name-ids

        .. warning:: This request is rate limited by Steam.

        :param item_nameid: special id of item class. Can be found only on listings page.
        :param lang:
        :param country:
        :param currency:
        :return: `ItemOrdersHistogram` dict
        :raises ApiError:
        """

        params = {
            "norender": 1,
            "language": lang or self.language,
            "country": country or self.country,
            "currency": currency or self.currency,
            "item_nameid": item_nameid,
            **kwargs,
        }
        r = await self.session.get(STEAM_URL.MARKET / "itemordershistogram", params=params)
        rj: ItemOrdersHistogram = await r.json()
        if not rj.get("success"):
            raise ApiError(f"Can't fetch item orders histogram for {item_nameid}.", rj)

        return rj

    async def fetch_item_orders_activity(
        self: "SteamPublicClient",
        item_name_id: int,
        *,
        lang: Language = None,
        country: str = None,
        currency: Currency = None,
        **kwargs: T_KWARGS,
    ) -> ItemOrdersActivity:
        """
        Do what described in method name.

        .. seealso::
            * https://github.com/Revadike/InternalSteamWebAPI/wiki/Get-Market-Item-Orders-Activity
            * https://github.com/somespecialone/steam-item-name-ids

        :param item_name_id: special id of item class. Can be found only on listings page.
        :param lang:
        :param country:
        :param currency:
        :return: `ItemOrdersActivity` dict
        :raises ApiError:
        """

        params = {
            "norender": 1,
            "language": lang or self.language,
            "country": country or self.country,
            "currency": currency or self.currency,
            "item_nameid": item_name_id,
            **kwargs,
        }
        r = await self.session.get(STEAM_URL.MARKET / "itemordersactivity", params=params)
        rj: ItemOrdersActivity = await r.json()
        if not rj.get("success"):
            raise ApiError(f"Can't fetch item orders activity for {item_name_id}.", rj)

        return rj

    @overload
    async def fetch_price_overview(
        self,
        obj: EconItem | ItemDescription,
        *,
        country: str = ...,
        currency: Currency = ...,
    ) -> PriceOverview:
        ...

    @overload
    async def fetch_price_overview(
        self,
        obj: str,
        app_id: int,
        *,
        country: str = ...,
        currency: Currency = ...,
    ) -> PriceOverview:
        ...

    async def fetch_price_overview(
        self: "SteamPublicClient",
        obj: str | EconItem | ItemDescription,
        app_id: int = None,
        *,
        country: str = None,
        currency: Currency = None,
        **kwargs: T_KWARGS,
    ) -> PriceOverview:
        """
        Fetch price data.

        .. warning:: This request is rate limited by Steam.

        :param obj:
        :param app_id:
        :param country:
        :param currency:
        :return: `PriceOverview` dict
        :raises ApiError:
        """

        if isinstance(obj, ITEM_DESCR_TUPLE):
            name = obj.market_hash_name
            app_id = obj.game.app_id
        else:  # str
            name = obj

        params = {
            "country": country or self.country,
            "currency": currency or self.currency,
            "market_hash_name": name,
            "appid": app_id,
            **kwargs,
        }
        r = await self.session.get(STEAM_URL.MARKET / "priceoverview", params=params)
        rj: PriceOverview = await r.json()
        if not rj.get("success"):
            raise ApiError(f"Can't fetch price overview for `{name}`.", rj)

        return rj

    @overload
    async def get_item_listings(
        self,
        obj: EconItem | ItemDescription,
        *,
        country: str = ...,
        currency: Currency = ...,
        query: str = ...,
        start: int = ...,
        count: int = ...,
    ) -> ITEM_MARKET_LISTINGS_DATA:
        ...

    @overload
    async def get_item_listings(
        self,
        obj: str,
        app_id: int,
        *,
        country: str = ...,
        currency: Currency = ...,
        query: str = ...,
        start: int = ...,
        count: int = ...,
    ) -> ITEM_MARKET_LISTINGS_DATA:
        ...

    async def get_item_listings(
        self: "SteamPublicClient",
        obj: str | EconItem | ItemDescription,
        app_id: int = None,
        *,
        country: str = None,
        currency: Currency = None,
        lang: str = None,
        query="",
        start: int = 0,
        count: int = 10,
        **kwargs: T_KWARGS,
    ) -> ITEM_MARKET_LISTINGS_DATA:
        """
        Fetch item listings from market.
        You can paginate by yourself passing `start` arg.

        .. warning:: This request is rate limited by Steam.

        :param obj: market hash name or `EconItem` or `ItemDescription`
        :param app_id:
        :param country:
        :param currency:
        :param lang:
        :param count: page size, Steam limit this size to 10 for now
        :param start: offset position
        :param query: raw search query
        :return: list of `MarketListing`, total listings count
        :raises ApiError:
        """

        if isinstance(obj, ITEM_DESCR_TUPLE):
            name = obj.market_hash_name
            app_id = obj.game[0]
        else:  # str
            name = obj

        base_url = STEAM_URL.MARKET / f"listings/{app_id}/{name}"
        params = {
            "filter": query,
            "country": country or self.country,
            "currency": currency or self.currency,
            "start": start,
            "count": count,
            "language": lang or self.language,
            **kwargs,
        }
        r = await self.session.get(base_url / "render/", params=params, headers={"Referer": str(base_url)})
        rj: dict[str, int | dict[str, dict]] = await r.json()
        if not rj.get("success"):
            raise ApiError(f"Can't fetch market listings for `{name}`.", rj)
        if not rj["total_count"] or not rj["assets"]:
            return [], 0

        item_descrs_map = {}
        econ_items_map = {}
        self._update_item_descrs_map_for_public(rj["assets"], item_descrs_map)
        self._parse_items_for_listings(rj["assets"], item_descrs_map, econ_items_map)

        return [
            MarketListing(
                id=int(l_data["listingid"]),
                item=econ_items_map[
                    create_ident_code(
                        l_data["asset"]["id"],
                        l_data["asset"]["appid"],
                        l_data["asset"]["contextid"],
                    )
                ],
                currency=Currency(int(l_data["currencyid"]) - 2000),
                price=int(l_data["price"]),
                fee=int(l_data["fee"]),
                converted_currency=Currency(int(l_data["converted_currencyid"]) - 2000),
                converted_fee=int(l_data["converted_fee"]),
                converted_price=int(l_data["converted_price"]),
            )
            for l_data in rj["listinginfo"].values()
        ], rj["total_count"]

    @classmethod
    def _update_item_descrs_map_for_public(
        cls,
        assets: dict[str, dict[str, dict[str, dict]]],
        item_descrs_map: dict[str, dict],
    ):
        for app_id, app_data in assets.items():
            for context_id, context_data in app_data.items():
                for asset_id, a_data in context_data.items():
                    key = create_ident_code(a_data["classid"], app_id)
                    item_descrs_map[key] = cls._create_item_description_kwargs(a_data, [a_data])

    @staticmethod
    def _parse_items_for_listings(
        data: dict[str, dict[str, dict[str, dict]]],
        item_descrs_map: dict[str, dict],
        econ_items_map: dict[str, MarketListingItem],
    ):
        for app_id, app_data in data.items():
            for context_id, context_data in app_data.items():
                for a_data in context_data.values():
                    key = create_ident_code(a_data["id"], app_id, context_id)
                    if key not in econ_items_map:
                        econ_items_map[key] = MarketListingItem(
                            asset_id=int(a_data["id"]),
                            market_id=0,  # market listing post init
                            unowned_id=int(a_data["unowned_id"]),
                            unowned_context_id=int(a_data["unowned_contextid"]),
                            **item_descrs_map[create_ident_code(a_data["classid"], app_id)],
                        )
