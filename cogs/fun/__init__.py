from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .fun import Fun
    from .fun import Roleplay

    await bot.add_cog(Fun(bot))
    await bot.add_cog(Roleplay(bot))
