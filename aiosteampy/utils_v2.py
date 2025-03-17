import datetime
from abc import abstractmethod

import aiohttp


class MailMessageProcessor:

    @abstractmethod
    async def get_last_mail_message_code(self):
        pass


class TimeAligner:
    _aligned = False
    _time_difference = 0

    @staticmethod
    async def get_steam_time_async():
        if not TimeAligner._aligned:
            await TimeAligner.align_time_async()
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp() + TimeAligner._time_difference)

    @staticmethod
    async def align_time_async():
        current_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        url = "https://api.steampowered.com/ITwoFactorService/QueryTime/v0001/"
        data = "steamid=0"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    response.raise_for_status()
                    json_response = await response.json()
                    server_time = int(json_response['response']['server_time'])
                    TimeAligner._time_difference = int(server_time - current_time)
                    TimeAligner._aligned = True
        except (aiohttp.ClientError, KeyError):
            return
