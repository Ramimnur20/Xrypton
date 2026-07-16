import discord
from discord.ext import commands
import secrets
from ..core.stats import Stats
from ..core.multiplier import get_multipliers

class MinesView(discord.ui.View):
    def __init__(self, ctx, user_id, amount, bombs, pool, redis, cache, session_id, demo=False):
        super().__init__(timeout=240)
        self.ctx = ctx
        self.user_id = user_id
        self.amount = amount
        self.bombs = bombs
        self.pool = pool
        self.redis = redis
        self.cache = cache
        self.session_id = session_id
        self.demo = demo
        self.rows = 4
        self.columns = 5
        total_tiles = self.rows * self.columns
        self.tiles = ["💣"] * bombs + ["🟩"] * (total_tiles - bombs)
        secrets.SystemRandom().shuffle(self.tiles)
        self.revealed = [False] * total_tiles
        self.clicks = 0
        self.multiplier = 1.00
        self.winnings = 0
        self.game_over = False
        self.first_click = True
        self.update_buttons()

    async def on_timeout(self):
        if self.game_over:
            return
        self.disable_all_buttons()
        await self.message.edit(view=self)
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.amount)
        await self.redis.delete(f"utils:mines:{self.user_id}:{self.session_id}")

    def get_multiplier(self):
        return get_multipliers(
            "mines",
            clicks=self.clicks,
            bombs=self.bombs,
            rows=self.rows,
            columns=self.columns,
        )

    def update_buttons(self):
        self.clear_items()
        total_tiles = self.rows * self.columns
        for i in range(total_tiles):
            if self.revealed[i]:
                if self.tiles[i] == "💣":
                    btn = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.danger, emoji="💣", disabled=True, row=i // self.columns)
                else:
                    btn = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.success, emoji="🟩", disabled=True, row=i // self.columns)
            else:
                btn = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.secondary, custom_id=str(i), disabled=self.game_over, row=i // self.columns)
                btn.callback = self.on_button_click
            self.add_item(btn)
        cashout = discord.ui.Button(label="Cashout", style=discord.ButtonStyle.green, custom_id="cashout", row=self.rows)
        exit_btn = discord.ui.Button(label="Exit", style=discord.ButtonStyle.red, custom_id="exit", row=self.rows)
        cashout.callback = self.on_cashout
        exit_btn.callback = self.on_exit
        self.add_item(cashout)
        self.add_item(exit_btn)

    async def on_button_click(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.warn("This is not your game.", ephemeral=True)
            return
        index = int(interaction.data["custom_id"])
        if self.revealed[index]:
            await interaction.response.defer()
            return
        self.revealed[index] = True
        if self.first_click:
            self.first_click = False
        if self.tiles[index] == "💣":
            for i, tile in enumerate(self.tiles):
                if tile == "💣":
                    self.revealed[i] = True
            self.update_buttons()
            self.game_over = True
            self.disable_all_buttons()
            await interaction.response.edit_message(view=self)
            embed = discord.Embed(description=f"💥 {interaction.user.mention} hit a mine and lost **{self.amount:,}** 💵" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.warn)
            await self.ctx.send(embed=embed)
            if not self.demo:
                stats = Stats(self.pool)
                await stats.log_game(self.user_id, "mines", "lose", self.amount)
            await self.redis.delete(f"utils:mines:{self.user_id}:{self.session_id}")
            return
        self.clicks += 1
        self.multiplier = self.get_multiplier()
        self.winnings = int(self.amount * self.multiplier)
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Tiles", value=f"{self.clicks}/{(self.rows * self.columns) - self.bombs}", inline=False)
        embed.set_field_at(1, name="Multiplier", value=f"{self.multiplier:.2f}x", inline=True)
        embed.set_field_at(2, name="Winnings", value=f"{self.winnings:,} 💵", inline=True)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_cashout(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.warn("This is not your game.", ephemeral=True)
            return
        if self.game_over or self.first_click:
            await interaction.response.warn("You can't cashout yet.", ephemeral=True)
            return
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.winnings)
        self.game_over = True
        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        embed = discord.Embed(description=f"{interaction.user.mention} cashed out **{self.winnings:,} 💵**" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.approve)
        await self.ctx.send(embed=embed)
        if not self.demo:
            stats = Stats(self.pool)
            await stats.log_game(self.user_id, "mines", "win", self.amount, self.winnings)
        await self.redis.delete(f"utils:mines:{self.user_id}:{self.session_id}")

    async def on_exit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.warn("This is not your game.", ephemeral=True)
            return
        if self.game_over or not self.first_click:
            await interaction.response.warn("Cannot exit now.", ephemeral=True)
            return
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.amount)
        self.game_over = True
        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)
        embed = discord.Embed(description=f"{interaction.user.mention} exited and got back **{self.amount:,} 💵**" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.approve)
        await self.ctx.send(embed=embed)
        await self.redis.delete(f"utils:mines:{self.user_id}:{self.session_id}")

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

async def _mines(ctx: commands.Context, amount: int, bombs: int, pool, redis, bot, cache):
    user = ctx.author
    demo = amount == 0
    bombs = max(1, min(bombs, 20))
    session_id = secrets.token_hex(8)
    key = f"utils:mines:{user.id}:{session_id}"
    if not demo:
        balance = await cache.get_balance(user.id)
        if balance < amount:
            await ctx.warn("You don't have enough money for that.", ephemeral=True)
            return
        await cache.subtract_balance(user.id, amount)
        await redis.setex(key, 300, amount)
    color = await bot.get_color(user.id)
    title = f"Mines Game {'(Demo)' if demo else f'{amount:,} 💵 — {bombs} 💣'}"
    total_tiles = 20
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Tiles", value=f"0/{total_tiles - bombs}", inline=False)
    embed.add_field(name="Multiplier", value="1.00x", inline=True)
    embed.add_field(name="Winnings", value=f"{amount:,} 💵", inline=True)
    view = MinesView(ctx, user.id, amount, bombs, pool, redis, cache, session_id, demo=demo)
    try:
        message = await ctx.send(embed=embed, view=view)
    except Exception:
        if not demo:
            await cache.add_balance(user.id, amount)
            await redis.delete(key)
        return
    view.message = message
