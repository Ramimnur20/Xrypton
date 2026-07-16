from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .games import Games

    await bot.add_cog(Games(bot))
