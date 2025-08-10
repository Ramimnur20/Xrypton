from base.bleed import Bot


async def setup(bot: Bot) -> None:
    from .information import Information

    await bot.add_cog(Information(bot))
