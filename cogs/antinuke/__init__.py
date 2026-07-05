from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .antinuke import AntiNuke
    from .antinuke import AntiNukeEvents

    await bot.add_cog(AntiNuke(bot))
    await bot.add_cog(AntiNukeEvents(bot))
