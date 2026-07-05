from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .miscellaneous import Miscellaneous
    from .miscellaneous import Customize

    await bot.add_cog(Customize(bot))
    await bot.add_cog(Miscellaneous(bot))
