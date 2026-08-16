from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .backup import Backup

    await bot.add_cog(Backup(bot))