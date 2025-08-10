from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .antiraid import Antiraid

    await bot.add_cog(Antiraid(bot))
