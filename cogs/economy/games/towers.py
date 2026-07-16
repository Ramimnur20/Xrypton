import discord
from discord.ext import commands
import secrets
from ..core.stats import Stats
from ..core.multiplier import get_multipliers

class TowersView(discord.ui.View):
    def __init__(self, ctx, user_id, amount, pool, redis, cache, session_id, demo=False):
        super().__init__(timeout=240)
        self.ctx = ctx
        self.user_id = user_id
        self.amount = amount
        self.pool = pool
        self.redis = redis
        self.cache = cache
        self.session_id = session_id
        self.demo = demo
        self.rows = 5
        self.columns = 3
        self.current_row = self.rows
        self.current_winnings = amount
        self.game_over = False
        self.first_click = True
        self.bomb_positions = [secrets.randbelow(self.columns) for _ in range(self.rows)]
        self.multipliers = get_multipliers("towers", rows=self.rows)
        self.revealed = [[False for _ in range(self.columns)] for _ in range(self.rows)]
        self.update_buttons()

    async def on_timeout(self):
        if self.game_over:
            return
        self.disable_all_buttons()
        await self.message.edit(view=self)
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.amount)
        await self.redis.delete(f"utils:towers:{self.user_id}:{self.session_id}")

    def update_buttons(self):
        self.clear_items()
        for row in range(self.rows):
            for col in range(self.columns):
                if self.revealed[row][col]:
                    if col == self.bomb_positions[row]:
                        button = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.danger, emoji="💣", row=row, disabled=True)
                    else:
                        button = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.success, row=row, disabled=True)
                else:
                    button = discord.ui.Button(label="\u200B", style=discord.ButtonStyle.secondary, row=row, custom_id=f"{row}_{col}", disabled=(row != self.current_row - 1 or self.game_over))
                    button.callback = self.on_button_click
                self.add_item(button)
        cashout = discord.ui.Button(label="Cashout", style=discord.ButtonStyle.green, disabled=self.game_over or self.first_click)
        cashout.callback = self.on_cashout
        self.add_item(cashout)
        exit_btn = discord.ui.Button(label="Exit", style=discord.ButtonStyle.red, disabled=self.game_over or not self.first_click)
        exit_btn.callback = self.on_exit
        self.add_item(exit_btn)

    async def on_button_click(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id or self.game_over or int(interaction.data["custom_id"].split("_")[0]) != self.current_row - 1:
            await interaction.response.warn("This is not your game.", ephemeral=True)
            return
        row = int(interaction.data["custom_id"].split("_")[0])
        col = int(interaction.data["custom_id"].split("_")[1])
        self.revealed[row][col] = True
        if self.first_click:
            self.first_click = False
        if col == self.bomb_positions[row]:
            for r in range(self.rows):
                if r <= self.current_row - 1:
                    self.revealed[r][self.bomb_positions[r]] = True
            self.update_buttons()
            self.game_over = True
            self.disable_all_buttons()
            await interaction.response.edit_message(view=self)
            embed = discord.Embed(description=f"💥 {interaction.user.mention} hit a bomb and lost **{self.amount:,}** 💵" + (" (Demo)" if self.demo else ""), color=self.ctx.config.colors.warn)
            await self.ctx.send(embed=embed)
            if not self.demo:
                stats = Stats(self.pool)
                await stats.log_game(self.user_id, "towers", "lose", self.amount)
            await self.redis.delete(f"utils:towers:{self.user_id}:{self.session_id}")
            return
        self.current_multiplier = self.multipliers[row]
        self.current_winnings = int(self.amount * self.current_multiplier)
        self.current_row -= 1
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Level", value=f"{self.rows - self.current_row}/{self.rows}", inline=False)
        embed.set_field_at(1, name="Multiplier", value=f"{self.current_multiplier:.2f}x", inline=True)
        embed.set_field_at(2, name="Winnings", value=f"{self.current_winnings:,} 💵", inline=True)
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
            await self.cache.add_balance(self.user_id, self.current_winnings)
        self.game_over = True
        self.disable_all_buttons()
        embed = discord.Embed(description=f"{interaction.user.mention} cashed out **{self.current_winnings:,} 💵**" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.approve)
        await interaction.response.edit_message(view=self)
        await self.ctx.send(embed=embed)
        if not self.demo:
            stats = Stats(self.pool)
            await stats.log_game(self.user_id, "towers", "win", self.amount, self.current_winnings)
        await self.redis.delete(f"utils:towers:{self.user_id}:{self.session_id}")

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
        embed = discord.Embed(description=f"{interaction.user.mention} exited and got back **{self.amount:,} 💵**" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.approve)
        await interaction.response.edit_message(view=self)
        await self.ctx.send(embed=embed)
        await self.redis.delete(f"utils:towers:{self.user_id}:{self.session_id}")

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

async def _towers(ctx: commands.Context, amount: int, pool, redis, bot, cache):
    user = ctx.author
    demo = amount == 0
    session_id = secrets.token_hex(8)
    key = f"utils:towers:{user.id}:{session_id}"
    if not demo:
        balance = await cache.get_balance(user.id)
        if balance < amount:
            await ctx.warn("You don't have enough money for that.", ephemeral=True)
            return
        await cache.subtract_balance(user.id, amount)
        await redis.setex(key, 300, amount)
    color = await bot.get_color(ctx.author.id)
    title = f"Towers Game {'(Demo)' if demo else f'{amount:,} 💵'}"
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Level", value="0/5", inline=False)
    embed.add_field(name="Multiplier", value="1.00x", inline=True)
    embed.add_field(name="Winnings", value=f"{amount:,} 💵", inline=True)
    view = TowersView(ctx, user.id, amount, pool, redis, cache, session_id, demo=demo)
    try:
        message = await ctx.send(embed=embed, view=view)
    except Exception:
        if not demo:
            await cache.add_balance(user.id, amount)
            await redis.delete(key)
        return
    view.message = message
