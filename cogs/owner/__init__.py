from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .owner import Owner

    await bot.add_cog(Owner(bot))
