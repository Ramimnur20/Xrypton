from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .fun import Fun

    await bot.add_cog(Fun(bot))
