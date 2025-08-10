from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .miscellaneous import Miscellaneous

    await bot.add_cog(Miscellaneous(bot))
