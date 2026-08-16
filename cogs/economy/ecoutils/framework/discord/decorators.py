import discord
from discord.ext import commands


async def check_donor(bot, user_id: int) -> bool:
    """Return True if the user should be treated as a donor / premium member.

    Xrypton has no donor role system, so we treat bot owners as donors so that
    premium-gated commands remain usable. Override this to integrate a real
    donor/premium check if one is added later.
    """
    return user_id in getattr(bot, "owner_ids", [])


def owner_only():
    async def predicate(ctx: commands.Context):
        return ctx.author.id in ctx.bot.owner_ids

    return commands.check(predicate)


def donor_only():
    async def predicate(ctx: commands.Context):
        return await check_donor(ctx.bot, ctx.author.id)

    return commands.check(predicate)
