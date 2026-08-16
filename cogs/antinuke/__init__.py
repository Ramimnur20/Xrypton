from base.Xrypton import Bot

async def setup(bot: Bot) -> None:
    from .antinuke import AntiNuke
    from .antinuke import AntiNukeEvents
    from .antinuke import Honeypot
    from .antinuke import Antiraid

    await bot.add_cog(Antiraid(bot))
    await bot.add_cog(Honeypot(bot))
    await bot.add_cog(AntiNuke(bot))
    await bot.add_cog(AntiNukeEvents(bot))
