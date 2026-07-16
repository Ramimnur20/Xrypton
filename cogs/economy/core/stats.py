import discord
import io
from cogs.economy.ecoutils.framework.tools.separator import makeseparator

class Stats:
    def __init__(self, pool):
        self.pool = pool

    async def ensure_entries(self, user_id: int):
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM economy_stats WHERE user_id=$1", user_id)
            if not exists:
                await conn.execute("INSERT INTO economy_stats (user_id) VALUES ($1)", user_id)

    async def log_game(self, user_id: int, game: str, result: str, amount: int, winnings: int = 0):
        await self.ensure_entries(user_id)
        async with self.pool.acquire() as conn:
            if result == "win":
                await conn.execute(
                    "UPDATE economy_stats SET total_games=total_games+1,total_wins=total_wins+1,total_won=total_won+$1 WHERE user_id=$2",
                    winnings or amount, user_id
                )
                await conn.execute(
                    """INSERT INTO economy_game_stats (user_id,game,games_played,wins,won)
                       VALUES ($1,$2,1,1,$3)
                       ON CONFLICT (user_id,game)
                       DO UPDATE SET games_played=economy_game_stats.games_played+1,
                                     wins=economy_game_stats.wins+1,
                                     won=economy_game_stats.won+$3""",
                    user_id, game, winnings or amount
                )
            elif result == "lose":
                await conn.execute(
                    "UPDATE economy_stats SET total_games=total_games+1,total_losses=total_losses+1,total_lost=total_lost+$1 WHERE user_id=$2",
                    amount, user_id
                )
                await conn.execute(
                    """INSERT INTO economy_game_stats (user_id,game,games_played,losses,lost)
                       VALUES ($1,$2,1,1,$3)
                       ON CONFLICT (user_id,game)
                       DO UPDATE SET games_played=economy_game_stats.games_played+1,
                                     losses=economy_game_stats.losses+1,
                                     lost=economy_game_stats.lost+$3""",
                    user_id, game, amount
                )
            elif result == "tie":
                await conn.execute(
                    "UPDATE economy_stats SET total_games=total_games+1,total_ties=total_ties+1 WHERE user_id=$1",
                    user_id
                )
                await conn.execute(
                    """INSERT INTO economy_game_stats (user_id,game,games_played,ties)
                       VALUES ($1,$2,1,1)
                       ON CONFLICT (user_id,game)
                       DO UPDATE SET games_played=economy_game_stats.games_played+1,
                                     ties=economy_game_stats.ties+1""",
                    user_id, game
                )

    async def fetch_overall(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM economy_stats WHERE user_id=$1", user_id)

    async def fetch_games(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM economy_game_stats WHERE user_id=$1 ORDER BY game ASC", user_id)

    async def has_stats(self, user_id: int):
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM economy_stats WHERE user_id=$1", user_id)
            return bool(exists)

    async def _add_separator_thumbnail(self, bot, embed, user_id):
        sep_bytes = await makeseparator(bot, user_id)
        sep_file = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
        embed.set_image(url="attachment://separator.png")
        return embed, sep_file

    async def build_embed(self, bot, user: discord.User, game: str = None):
        color = await bot.get_color(user.id)
        if not game:
            row = await self.fetch_overall(user.id)
            if not row:
                e = discord.Embed(description="No stats found for this user yet.\nPlay any economy game to start tracking your stats!", color=color)
                e.set_thumbnail(url=user.display_avatar.url)
                e, sep = await self._add_separator_thumbnail(bot, e, user.id)
                return e, sep
            total_games = row["total_games"]
            winrate = round((row["total_wins"] / total_games) * 100, 2) if total_games > 0 else 0
            e = discord.Embed(title=f"🎯 {user.name}'s Overall Stats", color=color)
            e.add_field(name="Games Played", value=f"{row['total_games']:,}")
            e.add_field(name="Wins", value=f"{row['total_wins']:,}")
            e.add_field(name="Losses", value=f"{row['total_losses']:,}")
            e.add_field(name="Ties", value=f"{row['total_ties']:,}")
            e.add_field(name="Total Won", value=f"{row['total_won']:,} 💵")
            e.add_field(name="Total Lost", value=f"{row['total_lost']:,} 💵")
            e.add_field(name="Win Rate", value=f"{winrate}%")
            e.set_author(name=user.name, icon_url=user.display_avatar.url)
            e, sep = await self._add_separator_thumbnail(bot, e, user.id)
            return e, sep
        else:
            async with self.pool.acquire() as conn:
                r = await conn.fetchrow("SELECT * FROM economy_game_stats WHERE user_id=$1 AND game=$2", user.id, game)
            if not r:
                e = discord.Embed(description=f"No stats found for {game.capitalize()}.", color=color)
                e.set_author(name=user.name, icon_url=user.display_avatar.url)
                e, sep = await self._add_separator_thumbnail(bot, e, user.id)
                return e, sep
            wr = round((r["wins"] / r["games_played"]) * 100, 2) if r["games_played"] > 0 else 0
            e = discord.Embed(title=f"🎮 {user.name}'s {game.capitalize()} Stats", color=color)
            e.add_field(name="Games Played", value=f"{r['games_played']:,}")
            e.add_field(name="Wins", value=f"{r['wins']:,}")
            e.add_field(name="Losses", value=f"{r['losses']:,}")
            e.add_field(name="Ties", value=f"{r['ties']:,}")
            e.add_field(name="Won", value=f"{r['won']:,} 💵")
            e.add_field(name="Lost", value=f"{r['lost']:,} 💵")
            e.add_field(name="Win Rate", value=f"{wr}%")
            e.set_author(name=user.name, icon_url=user.display_avatar.url)
            e, sep = await self._add_separator_thumbnail(bot, e, user.id)
            return e, sep

class StatsSelect(discord.ui.Select):
    def __init__(self, stats, bot, target_user, command_user, disabled=False):
        self.stats = stats
        self.bot = bot
        self.target_user = target_user
        self.command_user = command_user
        options = [
            discord.SelectOption(label="Overall Stats", value="overall", emoji="🌍"),
            discord.SelectOption(label="Towers", value="towers", emoji="🗼"),
            discord.SelectOption(label="Mines", value="mines", emoji="💣"),
            discord.SelectOption(label="Crossroad", value="crossroad", emoji="🐔"),
            discord.SelectOption(label="RPS", value="rps", emoji="✊"),
            discord.SelectOption(label="Coinflip", value="coinflip", emoji="🪙")
        ]
        super().__init__(placeholder="Select a game to view stats...", options=options, min_values=1, max_values=1, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        game = None if self.values[0] == "overall" else self.values[0]
        if interaction.user.id != self.command_user.id:
            embed, sep = await self.stats.build_embed(self.bot, self.target_user, game)
            await interaction.response.send_message(embed=embed, file=sep, ephemeral=True)
            return
        embed, sep = await self.stats.build_embed(self.bot, self.target_user, game)
        await interaction.response.edit_message(embed=embed, attachments=[sep], view=self.view)

class StatsView(discord.ui.View):
    def __init__(self, stats, bot, target_user, command_user, disabled=False):
        super().__init__(timeout=240)
        self.stats = stats
        self.bot = bot
        self.target_user = target_user
        self.command_user = command_user
        self.add_item(StatsSelect(stats, bot, target_user, command_user, disabled=disabled))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(view=None)
        except discord.NotFound:
            pass
