from .antinuke import AntiNuke

async def setup(bot):
    await bot.add_cog(AntiNuke(bot))