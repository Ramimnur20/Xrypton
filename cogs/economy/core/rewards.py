import discord
from discord import ui
from datetime import datetime, timedelta, timezone
from cogs.economy.ecoutils.framework.tools.separator import makeseparator
from cogs.economy.ecoutils.framework.discord.commands import CommandCache
import io, random

async def claim_daily(ctx, pool, cache, bot):
    user_id = ctx.author.id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_daily, daily_streak FROM economy WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO economy (user_id, last_daily, daily_streak) VALUES ($1, $2, $3)", user_id, None, 0)
            row = await conn.fetchrow("SELECT last_daily, daily_streak FROM economy WHERE user_id=$1", user_id)
    now = datetime.now(timezone.utc)
    last_claim = row["last_daily"]
    streak = row["daily_streak"]
    rewards = [1500, 3000, 5000, 10000, 20000, 35000, 50000]
    if last_claim:
        end = last_claim + timedelta(hours=24)
        if now < end:
            ts = int(end.timestamp())
            embed = discord.Embed(description=f"⏰ {ctx.author.mention}: You can claim again <t:{ts}:R>.", color=0xff6464)
            await ctx.send(embed=embed)
            return
    if last_claim and now <= last_claim + timedelta(hours=48):
        streak = min(streak + 1, 7)
    else:
        streak = 1
    reward = rewards[streak - 1]
    await cache.add_balance(user_id, reward)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE economy SET last_daily=$1, daily_streak=$2 WHERE user_id=$3", now, streak, user_id)
    embed = discord.Embed(description=f"🎉 {ctx.author.mention}: You claimed your daily reward!\n\n**Day {streak} Streak** — You earned **{reward:,}** 💲", color=await bot.get_color(user_id))
    await ctx.send(embed=embed)

async def claim_bonus(ctx, pool, cache, bot):
    user_id = ctx.author.id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT claimed_bonus FROM economy WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO economy (user_id, claimed_bonus) VALUES ($1, $2)", user_id, None)
            row = await conn.fetchrow("SELECT claimed_bonus FROM economy WHERE user_id=$1", user_id)
    now = datetime.now(timezone.utc)
    last_bonus = row["claimed_bonus"]
    if last_bonus:
        end = last_bonus + timedelta(minutes=10)
        if now < end:
            ts = int(end.timestamp())
            embed = discord.Embed(description=f"⏰ {ctx.author.mention}: You can claim a bonus again <t:{ts}:R>.", color=0xff6464)
            await ctx.send(embed=embed)
            return
    async with pool.acquire() as conn:
        await conn.execute("UPDATE economy SET claimed_bonus=$1 WHERE user_id=$2", now, user_id)
    embed = discord.Embed(description=f"{ctx.author.mention}: Choose a button to reveal your prize!", color=await bot.get_color(user_id))
    class BonusView(ui.View):
        def __init__(self, user, pool, cache):
            super().__init__(timeout=240)
            self.user = user
            self.pool = pool
            self.cache = cache
            self.prizes = [random.randint(200, 1000) for _ in range(3)]
            self.clicked = False
            self.message = None
        @ui.button(label="\u200B", style=discord.ButtonStyle.primary, row=0)
        async def b1(self, i, b): await self.pick(i, 0)
        @ui.button(label="\u200B", style=discord.ButtonStyle.primary, row=0)
        async def b2(self, i, b): await self.pick(i, 1)
        @ui.button(label="\u200B", style=discord.ButtonStyle.primary, row=0)
        async def b3(self, i, b): await self.pick(i, 2)
        async def pick(self, i, idx):
            if i.user.id != self.user.id:
                return await i.response.warn("This bonus is not for you!", ephemeral=True)
            if self.clicked:
                return await i.response.warn("You've already claimed your bonus!", ephemeral=True)
            self.clicked = True
            for x, child in enumerate(self.children):
                child.disabled = True
                child.label = f"{self.prizes[x]} 💲"
                if x == idx:
                    child.style = discord.ButtonStyle.success
            prize = self.prizes[idx]
            await self.cache.add_balance(self.user.id, prize)
            async with self.pool.acquire() as conn:
                await conn.execute("UPDATE economy SET money = money + $1 WHERE user_id=$2", prize, self.user.id)
            embed = i.message.embeds[0]
            embed.description = f"🎉 {self.user.mention}: You won **{prize:,}** 💲!"
            embed.color = 0xa4ec7c
            await i.response.edit_message(embed=embed, view=self)
        async def on_timeout(self):
            for c in self.children:
                c.disabled = True
            if self.message:
                await self.message.edit(view=self)
    view = BonusView(ctx.author, pool, cache)
    msg = await ctx.send(embed=embed, view=view)
    view.message = msg

async def claim_premium_monthly(ctx, pool, cache, bot):
    user_id = ctx.author.id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT premium_monthly FROM economy WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO economy (user_id, premium_monthly) VALUES ($1, $2)", user_id, None)
            row = await conn.fetchrow("SELECT premium_monthly FROM economy WHERE user_id=$1", user_id)
    now = datetime.now(timezone.utc)
    last_claim = row["premium_monthly"]
    if last_claim:
        end = last_claim + timedelta(days=30)
        if now < end:
            ts = int(end.timestamp())
            embed = discord.Embed(description=f"⏰ {ctx.author.mention}: You can claim again <t:{ts}:R>.", color=0xff6464)
            return await ctx.send(embed=embed)
    reward = 1_000_000
    await cache.add_balance(user_id, reward)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE economy SET premium_monthly=$1 WHERE user_id=$2", now, user_id)
    embed = discord.Embed(description=f"🎉 {ctx.author.mention}: You claimed your **monthly Premium reward**!\n\nYou earned **{reward:,}** 💲", color=await bot.get_color(user_id))
    await ctx.send(embed=embed)

async def claim_join_bonus(ctx, pool, cache, bot, SERVER_ID):
    user_id = ctx.author.id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT join_bonus_claimed FROM economy WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO economy (user_id, join_bonus_claimed) VALUES ($1, $2)", user_id, False)
            row = await conn.fetchrow("SELECT join_bonus_claimed FROM economy WHERE user_id=$1", user_id)

    if row["join_bonus_claimed"]:
        return await ctx.warn("You already claimed your Join Bonus.")

    key = f"joinbonus_cooldown:{user_id}"
    if await bot.redis.get(key):
        return await ctx.warn("Slow down. Try again in a moment.")
    await bot.redis.set(key, "1", ex=10)

    guild = bot.get_guild(SERVER_ID)
    if not guild:
        return await ctx.warn("The server is unavailable.")

    member = guild.get_member(user_id)
    if not member:
        embed = discord.Embed(
            description="Claim a free 💲 **50,000** by joining our Support server [here](https://discord.gg/utilsbot) and re-running the command.",
            color=await bot.get_color(user_id)
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join utils's server", url="https://discord.gg/utilsbot"))
        return await ctx.send(embed=embed, view=view)

    await cache.add_balance(user_id, 50000)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE economy SET join_bonus_claimed=TRUE WHERE user_id=$1", user_id)

    embed = discord.Embed(
        description=f"🎉 {ctx.author.mention}: You claimed your Join Bonus and received **50,000** 💲!",
        color=await bot.get_color(user_id)
    )
    await ctx.send(embed=embed)

async def get_cooldowns(ctx, pool, bot):
    from cogs.economy.ecoutils.framework.discord.commands import CommandCache
    user_id = ctx.author.id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_daily, claimed_bonus, last_fish, premium_monthly, join_bonus_claimed FROM economy WHERE user_id=$1", user_id)
        if not row:
            await conn.execute("INSERT INTO economy (user_id) VALUES ($1)", user_id)
            row = await conn.fetchrow("SELECT last_daily, claimed_bonus, last_fish, premium_monthly, join_bonus_claimed FROM economy WHERE user_id=$1", user_id)
    now = datetime.now(timezone.utc)
    daily = row["last_daily"]
    bonus = row["claimed_bonus"]
    fish = row["last_fish"]
    prem = row["premium_monthly"]
    joinbonus_claimed = row["join_bonus_claimed"]
    if not daily:
        daily_text = "`Available`"
    else:
        end = daily + timedelta(hours=24)
        daily_text = f"<t:{int(end.timestamp())}:R>" if now < end else "`Available`"
    if not bonus:
        bonus_text = "`Available`"
    else:
        end = bonus + timedelta(minutes=10)
        bonus_text = f"<t:{int(end.timestamp())}:R>" if now < end else "`Available`"
    if not fish:
        fish_text = "`Available`"
    else:
        end = fish + timedelta(minutes=5)
        fish_text = f"<t:{int(end.timestamp())}:R>" if now < end else "`Available`"
    if not prem:
        prem_text = "`Available`"
    else:
        end = prem + timedelta(days=30)
        prem_text = f"<t:{int(end.timestamp())}:R>" if now < end else "`Available`"
    embed = discord.Embed(title=f"{ctx.author.name}'s Cooldowns", color=await bot.get_color(user_id))
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.add_field(name="Daily (24h)", value=daily_text + f"\n{bot.config.emojis.context.cash} 1,500 - 50,000", inline=True)
    embed.add_field(name="Bonus (10m)", value=bonus_text + f"\n{bot.config.emojis.context.cash} 200 - 1,000", inline=True)
    embed.add_field(name="Fishing (5m)", value=fish_text + f"\n🐟 & {bot.config.emojis.context.cash}", inline=True)
    embed.add_field(name=f"{bot.config.emojis.context.premium} Monthly (30d)", value=prem_text + f"\n{bot.config.emojis.context.cash} 1,000,000", inline=True)
    if not joinbonus_claimed:
        joinbonus = await CommandCache.get_mention(bot, "eco joinbonus")
        embed.add_field(
            name="Join Bonus (One Time)",
            value=f"{joinbonus}\n{bot.config.emojis.context.cash} 50,000",
            inline=True
        )
    sep_bytes = await makeseparator(bot, ctx.author.id)
    sep = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
    embed.set_image(url="attachment://separator.png")
    await ctx.send(embed=embed, file=sep)
