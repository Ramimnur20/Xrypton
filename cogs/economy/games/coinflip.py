import discord
import secrets
import asyncio
from ..core.stats import Stats

async def _coinflip(ctx, amount: int, side: str, pool, redis, bot, cache):
    user = ctx.author
    demo = amount == 0
    balance_before = await cache.get_balance(user.id)
    if not demo:
        if balance_before < amount:
            await ctx.warn("You don't have enough money for that.")
            return
        await cache.subtract_balance(user.id, amount)
    color = await bot.get_color(user.id)
    flipping = discord.Embed(description=f"<a:coin_peng:1436922489820282910> {user.mention}: flips a coin..", color=color)
    message = await ctx.send(embed=flipping)
    await asyncio.sleep(2)
    result = "heads" if secrets.randbelow(2) == 0 else "tails"
    moji = "<:coinheads:1377329015886581922>" if result == "heads" else "<:cointails:1377328997767057499>"
    won = (side.lower() == result)
    stats = Stats(pool)
    if not demo:
        if won:
            await cache.add_balance(user.id, amount * 2)
            await stats.log_game(user.id, "coinflip", "win", amount, amount)
            new_balance = balance_before + amount
            desc = f"{moji} It's **{result.capitalize()}**!\n> You won **{amount:,}** 💵, you have **{new_balance:,}** 💵"
            color = ctx.config.colors.information
        else:
            await stats.log_game(user.id, "coinflip", "lose", amount)
            new_balance = balance_before - amount
            desc = f"{moji} You chose **{side.capitalize()}**, but it was **{result.capitalize()}**\n> You lost **{amount:,}** 💵, you have **{new_balance:,}** 💵"
            color = ctx.config.colors.warn
    else:
        desc = f"{moji} It's **{result.capitalize()}**!\n> Bet made using demo mode, nothing won/lost."
        color = ctx.config.colors.information
    result_embed = discord.Embed(description=desc, color=color)
    await message.edit(embed=result_embed)
