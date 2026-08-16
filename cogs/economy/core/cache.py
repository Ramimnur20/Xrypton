class Cache:
    def __init__(self, redis, pool):
        self.redis = redis
        self.pool = pool

    async def get_balance(self, user_id: int):
        key = f"eco:{user_id}:money"
        cached = await self.redis.get(key)
        if cached is not None:
            return int(cached)
        async with self.pool.acquire() as conn:
            balance = await conn.fetchval("SELECT money FROM economy WHERE user_id=$1", user_id)
        if balance is not None:
            await self.redis.setex(key, 30, balance)
        return balance or 0

    async def set_balance(self, user_id: int, balance: int):
        key = f"eco:{user_id}:money"
        await self.redis.delete(key)
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE economy SET money=$1 WHERE user_id=$2", balance, user_id)

    async def add_balance(self, user_id: int, amount: int):
        current = await self.get_balance(user_id)
        new_balance = current + amount
        await self.redis.delete(f"eco:{user_id}:money")
        await self.set_balance(user_id, new_balance)
        return new_balance

    async def subtract_balance(self, user_id: int, amount: int):
        current = await self.get_balance(user_id)
        new_balance = max(0, current - amount)
        await self.redis.delete(f"eco:{user_id}:money")
        await self.set_balance(user_id, new_balance)
        return new_balance

    async def invalidate(self, user_id: int):
        await self.redis.delete(f"eco:{user_id}:money")
