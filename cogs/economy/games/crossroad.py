import discord
from discord.ext import commands
import secrets
from ..core.stats import Stats
from ..core.multiplier import get_multipliers

class CrossroadView(discord.ui.View):
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
        self.length = 10
        self.position = 0
        self.current_winnings = amount
        self.game_over = False
        self.first_click = True
        self.multipliers = get_multipliers("crossroad", length=self.length)
        self.cars = [False for _ in range(self.length)]
        self.update_buttons()

    async def on_timeout(self):
        if self.game_over:
            return
        self.disable_all_buttons()
        await self.message.edit(view=self)
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.amount)
        await self.redis.delete(f"utils:crossroad:{self.user_id}:{self.session_id}")

    def render_track(self, dead=False):
        track = []
        for i in range(self.length):
            if i == self.position:
                track.append("💀" if dead else "🐔")
            elif self.cars[i]:
                track.append("🚗")
            else:
                track.append("⬜")
        return " ".join(track)

    def update_buttons(self):
        self.clear_items()
        move = discord.ui.Button(label="Move", style=discord.ButtonStyle.green, disabled=self.game_over)
        move.callback = self.on_move
        cashout = discord.ui.Button(label="Cashout", style=discord.ButtonStyle.blurple, disabled=self.game_over or self.first_click)
        cashout.callback = self.on_cashout
        exit_btn = discord.ui.Button(label="Exit", style=discord.ButtonStyle.red, disabled=self.game_over or not self.first_click)
        exit_btn.callback = self.on_exit
        self.add_item(move)
        self.add_item(cashout)
        self.add_item(exit_btn)

    async def on_move(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.warn("This is not your game.", ephemeral=True)
            return
        if self.first_click:
            self.first_click = False
        if self.position >= self.length - 1:
            await interaction.response.warn("You already crossed all lanes.", ephemeral=True)
            return
        for i in range(self.length):
            if i == 0:
                danger = 36
            elif i == 1:
                danger = 38
            elif i == 2:
                danger = 42
            elif i == 3:
                danger = 46
            else:
                danger = 50

            self.cars[i] = secrets.randbelow(100) < danger

            self.cars[i] = secrets.randbelow(100) < danger
        self.position += 1
        if self.cars[self.position]:
            self.game_over = True
            self.disable_all_buttons()
            embed = interaction.message.embeds[0]
            embed.description = self.render_track(dead=True)
            await interaction.response.edit_message(embed=embed, view=self)
            await self.ctx.send(embed=discord.Embed(description=f"💥 {interaction.user.mention} got hit and lost **{self.amount:,}** 💵" + (" (Demo)" if self.demo else ""), color=self.ctx.config.colors.warn))
            if not self.demo:
                stats = Stats(self.pool)
                await stats.log_game(self.user_id, "crossroad", "lose", self.amount)
            await self.redis.delete(f"utils:crossroad:{self.user_id}:{self.session_id}")
            return
        self.current_multiplier = self.multipliers[self.position]
        self.current_winnings = int(self.amount * self.current_multiplier)
        embed = interaction.message.embeds[0]
        embed.description = self.render_track()
        embed.set_field_at(0, name="Position", value=f"{self.position+1}/{self.length}", inline=False)
        embed.set_field_at(1, name="Multiplier", value=f"{self.current_multiplier:.2f}x", inline=True)
        embed.set_field_at(2, name="Winnings", value=f"{self.current_winnings:,} 💵", inline=True)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)
        if self.position >= self.length - 1:
            if not self.demo:
                await self.cache.add_balance(self.user_id, self.current_winnings)
            self.game_over = True
            self.disable_all_buttons()
            win_embed = discord.Embed(description=f"🐔 {interaction.user.mention} successfully crossed and won **{self.current_winnings:,}** 💵" + (" (Demo)" if self.demo else ""), color=self.ctx.config.colors.approve)
            await self.ctx.send(embed=win_embed)
            if not self.demo:
                stats = Stats(self.pool)
                await stats.log_game(self.user_id, "crossroad", "win", self.amount, self.current_winnings)
            await self.redis.delete(f"utils:crossroad:{self.user_id}:{self.session_id}")

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
            await stats.log_game(self.user_id, "crossroad", "win", self.amount, self.current_winnings)
        await self.redis.delete(f"utils:crossroad:{self.user_id}:{self.session_id}")

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
        embed = discord.Embed(description=f"{interaction.user.mention} exited and got back **{self.amount:,}** 💵" + (" *(Demo)*" if self.demo else ""), color=self.ctx.config.colors.approve)
        await interaction.response.edit_message(view=self)
        await self.ctx.send(embed=embed)
        await self.redis.delete(f"utils:crossroad:{self.user_id}:{self.session_id}")

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

async def _crossroad(ctx: commands.Context, amount: int, pool, redis, bot, cache):
    user = ctx.author
    demo = amount == 0
    session_id = secrets.token_hex(8)
    key = f"utils:crossroad:{user.id}:{session_id}"
    if not demo:
        balance = await cache.get_balance(user.id)
        if balance < amount:
            await ctx.warn("You don't have enough money for that.", ephemeral=True)
            return
        await cache.subtract_balance(user.id, amount)
        await redis.setex(key, 300, amount)
    color = await bot.get_color(ctx.author.id)
    title = f"Chicken Crossroad {'(Demo)' if demo else f'{amount:,} 💵'}"
    embed = discord.Embed(title=title, color=color)
    embed.description = "🐔 ⬜ ⬜ ⬜ ⬜ ⬜ ⬜ ⬜ ⬜ ⬜"
    embed.add_field(name="Position", value="1/10", inline=False)
    embed.add_field(name="Multiplier", value="1.00x", inline=True)
    embed.add_field(name="Winnings", value=f"{amount:,} 💵", inline=True)
    view = CrossroadView(ctx, user.id, amount, pool, redis, cache, session_id, demo=demo)
    try:
        message = await ctx.send(embed=embed, view=view)
    except Exception:
        if not demo:
            await cache.add_balance(user.id, amount)
            await redis.delete(key)
        return
    view.message = message
