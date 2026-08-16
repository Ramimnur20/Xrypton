from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .levels import Levels
    from .levels import LevelEvents

    await bot.add_cog(Levels(bot))
    await bot.add_cog(LevelEvents(bot))