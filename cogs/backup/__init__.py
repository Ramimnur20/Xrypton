from .backup import Backup

async def setup(bot):
    await bot.add_cog(Backup(bot))