from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .antinuke import Antinuke

    await bot.add_cog(Antinuke(bot))