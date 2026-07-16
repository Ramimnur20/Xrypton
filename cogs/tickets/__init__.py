from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .tickets import Tickets

    await bot.add_cog(Tickets(bot))
