from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .moderation import Moderation
    from .snipe import Snipe

    await bot.add_cog(Snipe(bot))
    await bot.add_cog(Moderation(bot))
