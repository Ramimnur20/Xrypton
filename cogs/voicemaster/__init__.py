from base.Xrypton import Bot


async def setup(bot: Bot) -> None:
    from .voicemaster import Voicemaster
    from .events import VoicemasterEvents

    await bot.add_cog(Voicemaster(bot))
    await bot.add_cog(VoicemasterEvents(bot))