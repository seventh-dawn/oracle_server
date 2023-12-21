import asyncio
import json
import os
import sched
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pyinjective.async_client import AsyncClient
from pyinjective.core.network import Network


@dataclass
class NativeCoinData:
    pair: str
    denom: str
    feed: Optional[str] = None
    decimals: int = 6


DAMPENING = 0.8
TIME_INTERVAL = 60
N = 3
DATA_TIMEOUT = 120

SAVE_PATH = Path("./last_rounds.json")
ARCHIVE_PATH = Path("./old")
KATANA_PAIR = "inj17u06g05sc3jyc9c94qmnquw7gsty7qwu0epssz"
KATANA_DENOM = "factory/inj1vwn4x08hlactxj3y3kuqddafs2hhqzapruwt87/katana"
INJ_DENOM = "inj"
INJ_USDT_PAIR = "inj1d7ru9e8qcs70qp97ffwgya7lt5qpe7r646nufu"
USDT_DENOM = "peggy0xdAC17F958D2ee523a2206206994597C13D831ec7"
DATA = {}
CLIENT: AsyncClient

KATANA_INFO = NativeCoinData(KATANA_PAIR, KATANA_DENOM)
COINS: list[NativeCoinData] = [KATANA_INFO]

s = sched.scheduler(time.time, time.sleep)


class Scheduler:
    interval: int
    last_tick: int


def periodic(scheduler, interval, action, actionargs=()):
    scheduler.enter(interval, 1, periodic, (scheduler, interval, action, actionargs))
    action(*actionargs)


def get_rounds():
    last_round = DATA["history"][-1]


def save():
    json.dump(DATA, open(SAVE_PATH, "w"), indent=2)


def load():
    return json.load(open(SAVE_PATH))


def init_data():
    return {"last_round": None, "history": []}


class BadAnswer(Exception):
    pass


async def get_inj_last_round():
    prices = await CLIENT.get_bank_balances(INJ_USDT_PAIR)
    balances = prices.balances
    usdt_amount = [row.amount for row in balances if row.denom == USDT_DENOM]
    inj_amount = [row.amount for row in balances if row.denom == INJ_DENOM]
    assert len(usdt_amount) == 1, BadAnswer
    assert len(inj_amount) == 1, BadAnswer
    return int(usdt_amount[0]) * 10**12 / int(inj_amount[0])


async def get_native_last_round(native_coin: NativeCoinData, inj_price: float):
    prices = await CLIENT.get_bank_balances(native_coin.pair)
    balances = prices.balances
    native_amount = [row.amount for row in balances if row.denom == native_coin.denom]
    inj_amount = [row.amount for row in balances if row.denom == INJ_DENOM]
    assert len(native_amount) == 1, BadAnswer
    assert len(inj_amount) == 1, BadAnswer
    return (
        int(inj_amount[0]) / int(native_amount[0]) / 10 ** (18 - native_coin.decimals) * inj_price
    )


def get_price(denom, coeff, n=3):
    global DATA
    prices = [row[denom] for row in DATA["history"][-n:]]
    return (
        sum([prices[-i - 1] * coeff ** (i) for i in range(n)]) / (1 - coeff ** (n)) * (1 - coeff)
    )


async def fetch_current_data():
    inj_price = await get_inj_last_round()
    DATA["history"].append({"id": time.time(), INJ_DENOM: inj_price})
    for coin in COINS:
        price = await get_native_last_round(coin, inj_price)
        DATA["history"][-1][coin.denom] = price
    print("got step", DATA["history"][-1]["id"])
    save()


async def main() -> None:
    global CLIENT
    global DATA
    try:
        DATA = load()
        if time.time() - DATA["history"][-1]["id"] > DATA_TIMEOUT:
            os.makedirs(ARCHIVE_PATH, exist_ok=True)
            shutil.copyfile(SAVE_PATH, ARCHIVE_PATH / str(time.time()))
            DATA = init_data()
    except FileNotFoundError:
        DATA = init_data()
    network = Network.mainnet()
    CLIENT = AsyncClient(network)
    for _ in range(3):
        await fetch_current_data()
        time.sleep(10)
    print(get_price(KATANA_INFO.denom, coeff=DAMPENING))


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
