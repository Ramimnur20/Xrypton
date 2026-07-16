from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .moderation import Moderation

    await bot.add_cog(Moderation(bot))
