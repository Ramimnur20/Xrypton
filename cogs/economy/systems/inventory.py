import discord
import io
import json
from cogs.economy.ecoutils.framework.pagination import Paginator
from cogs.economy.ecoutils.framework.tools.separator import makeseparator
from .items import ITEMS

CATEGORY_NAMES = {
    "tool": "Tools",
    "storage": "Storage",
    "fish": "Fish",
}

class InventorySystem:
    def __init__(self, pool):
        self.pool = pool
        self.bot = None

    def attach(self, bot):
        self.bot = bot

    async def add_item(self, user_id: int, item_id: str, amount: int = 1):
        lock_key = f"inventory_lock:{user_id}"
        async with self.bot.redis.lock(lock_key, timeout=5):
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO economy_inventory (user_id, item_id, amount)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, item_id)
                    DO UPDATE SET amount = economy_inventory.amount + EXCLUDED.amount
                    """,
                    user_id,
                    item_id,
                    amount,
                )

    async def remove_item(self, user_id: int, item_id: str, amount: int = 1):
        lock_key = f"inventory_lock:{user_id}"
        async with self.bot.redis.lock(lock_key, timeout=5):
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT amount FROM economy_inventory WHERE user_id=$1 AND item_id=$2",
                    user_id,
                    item_id,
                )
                if not row:
                    return False
                if row["amount"] < amount:
                    return False
                new_amount = row["amount"] - amount
                if new_amount <= 0:
                    await conn.execute(
                        "DELETE FROM economy_inventory WHERE user_id=$1 AND item_id=$2",
                        user_id,
                        item_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE economy_inventory SET amount=$3 WHERE user_id=$1 AND item_id=$2",
                        user_id,
                        item_id,
                        new_amount,
                    )
                return True

    async def get_inventory(self, user_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT item_id, amount FROM economy_inventory WHERE user_id=$1",
                user_id,
            )
        return {r["item_id"]: r["amount"] for r in rows}

    async def has_item(self, user_id: int, item_id: str):
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT amount FROM economy_inventory WHERE user_id=$1 AND item_id=$2",
                user_id,
                item_id,
            )
        return bool(val)

    async def get_fishbag(self, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT fish FROM economy_fishbag WHERE user_id=$1",
                user_id,
            )
        if not row:
            return {}
        raw = row["fish"]
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}

    async def set_fishbag(self, user_id: int, fish_data: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO economy_fishbag (user_id, fish)
                VALUES ($1, $2)
                ON CONFLICT (user_id)
                DO UPDATE SET fish = EXCLUDED.fish
                """,
                user_id,
                json.dumps(fish_data),
            )

    async def add_fish(self, user_id: int, fish_id: str, amount: int = 1):
        lock_key = f"fishbag_lock:{user_id}"
        async with self.bot.redis.lock(lock_key, timeout=5):
            fish_data = await self.get_fishbag(user_id)
            fish_data[fish_id] = fish_data.get(fish_id, 0) + amount
            await self.set_fishbag(user_id, fish_data)

    async def remove_fish(self, user_id: int, fish_id: str, amount: int = 1):
        lock_key = f"fishbag_lock:{user_id}"
        async with self.bot.redis.lock(lock_key, timeout=5):
            fish_data = await self.get_fishbag(user_id)
            if fish_id not in fish_data or fish_data[fish_id] < amount:
                return False
            new_amount = fish_data[fish_id] - amount
            if new_amount <= 0:
                del fish_data[fish_id]
            else:
                fish_data[fish_id] = new_amount
            await self.set_fishbag(user_id, fish_data)
            return True

    async def build_embed_pages(self, ctx, items: dict, sep_url: str, color: int):
        lines = []
        for item_id, amt in items.items():
            item = ITEMS[item_id]
            emoji = item["emoji"]
            name = item["name"]
            category = CATEGORY_NAMES.get(item["type"], item["type"].title())
            lines.append(f"### {emoji} {name} ─ {amt}\n<:pointdrl:1318643571317801040> {category}")
        chunks = [lines[i:i + 10] for i in range(0, len(lines), 10)]
        pages = []
        for chunk in chunks:
            embed = discord.Embed(description="\n".join(chunk), color=color)
            embed.set_author(name=f"{ctx.author.name}'s Inventory", icon_url=ctx.author.display_avatar.url)
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            embed.set_image(url=sep_url)
            pages.append(embed)
        return pages

    async def send_inventory(self, ctx, user_id: int):
        items = await self.get_inventory(user_id)
        if not items:
            await ctx.warn("Your inventory is empty.")
            return
        sep_bytes = await makeseparator(self.bot, ctx.author.id)
        sep_file = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
        sep_url = "attachment://separator.png"
        color = await self.bot.get_color(ctx.author.id)
        pages = await self.build_embed_pages(ctx, items, sep_url, color)
        paginator = Paginator(ctx, pages, hide_nav=False, hide_footer=True, arrows_only=True, only_for_owner=True)
        msg = await paginator.start(file=sep_file)
        paginator.message = msg
