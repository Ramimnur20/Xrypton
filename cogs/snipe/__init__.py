from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .snipe import Snipe

    await bot.add_cog(Snipe(bot))
