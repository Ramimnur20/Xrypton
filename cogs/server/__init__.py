from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .server import Server

    await bot.add_cog(Server(bot))
