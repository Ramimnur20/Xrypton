import random
from datetime import datetime, timedelta, timezone
from .items import ITEMS, RARITY_WEIGHT, get_fish_items

async def get_fishing_data(pool, user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_fish FROM economy WHERE user_id=$1",
            user_id
        )
        if not row:
            await conn.execute(
                "INSERT INTO economy (user_id, last_fish) VALUES ($1, $2)",
                user_id, None
            )
            return None
        return row["last_fish"]

async def update_fishing_time(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE economy SET last_fish=$1 WHERE user_id=$2",
            datetime.now(timezone.utc), user_id
        )

def choose_fish():
    fishes = get_fish_items()
    pool = []
    for f_id, data in fishes.items():
        weight = RARITY_WEIGHT.get(data["rarity"], 1)
        pool.extend([f_id] * weight)
    fish_id = random.choice(pool)
    return fish_id, ITEMS[fish_id]

async def fish_action(user_id: int, pool, cache, inventory):
    last = await get_fishing_data(pool, user_id)
    now = datetime.now(timezone.utc)
    cd = timedelta(minutes=5)
    if last and now < last + cd:
        ts = int((last + cd).timestamp())
        return {
            "status": "cooldown",
            "retry": ts
        }

    rod = await inventory.has_item(user_id, "fishing_rod")
    if not rod:
        return {"status": "no_rod"}

    fish_id, data = choose_fish()

    bag = await inventory.has_item(user_id, "fish_bag")

    if bag:
        await inventory.add_fish(user_id, fish_id, 1)
        await update_fishing_time(pool, user_id)
        return {
            "status": "stored",
            "id": fish_id,
            "name": data["name"],
            "emoji": data["emoji"],
            "rarity": data["rarity"]
        }

    await cache.add_balance(user_id, data["value"])
    await update_fishing_time(pool, user_id)
    return {
        "status": "paid",
        "id": fish_id,
        "name": data["name"],
        "emoji": data["emoji"],
        "value": data["value"],
        "rarity": data["rarity"]
    }
