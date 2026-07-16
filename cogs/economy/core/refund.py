from discord.ext import tasks

class RefundSystem:
    def __init__(self, cog):
        self.cog = cog
        self.bot = cog.bot
        self.pool = cog.pool
        self.redis = cog.redis
        self.cache = cog.cache
        self.bot.loop.create_task(self.refund_stuck_games())

    async def refund_stuck_games(self):
        await self.bot.wait_until_ready()
        keys = await self.redis.keys("utils:*:*")
        for key in keys:
            parts = key.split(":")
            if len(parts) < 3:
                continue
            try:
                amount = await self.redis.get(key)
                if not amount:
                    continue
                amount = int(amount)
                if amount <= 0:
                    continue
                if key.startswith("utils:wager_rps:"):
                    if len(parts) < 5:
                        continue
                    p1, p2 = int(parts[2]), int(parts[3])
                    await self.cache.add_balance(p1, amount)
                    await self.cache.add_balance(p2, amount)
                    await self.redis.delete(key)
                    continue
                user_id = int(parts[2])
                await self.cache.add_balance(user_id, amount)
                await self.redis.delete(key)
            except Exception:
                continue
