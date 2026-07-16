import discord
from discord.ext import commands
import random
import secrets
from ..core.stats import Stats

class RPSView(discord.ui.View):
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
        self.choice = None
        self.house_choice = None
        self.game_over = False
        self.choices = {
            "rock": "<a:rock:1361492026901925988>",
            "paper": "<a:paper:1361492022820733122>",
            "scissors": "<a:scissors:1361492016894316802>",
        }
        self.update_buttons()

    async def on_timeout(self):
        if self.game_over:
            return
        self.disable_all_buttons()
        await self.message.edit(view=self)
        if not self.demo:
            await self.cache.add_balance(self.user_id, self.amount)
        await self.redis.delete(f"utils:rps:{self.user_id}:{self.session_id}")

    def update_buttons(self):
        self.clear_items()
        for name, emoji in self.choices.items():
            btn = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=emoji, custom_id=name, disabled=self.game_over)
            btn.callback = self.on_choice
            self.add_item(btn)

    async def on_choice(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.warn("This game isn't for you or has ended.", ephemeral=True)
            return
        self.choice = interaction.data["custom_id"]
        self.house_choice = random.choice(list(self.choices.keys()))
        self.game_over = True
        self.disable_all_buttons()
        if self.choice == self.house_choice:
            result = "tie"
        elif (self.choice == "rock" and self.house_choice == "scissors") or (self.choice == "paper" and self.house_choice == "rock") or (self.choice == "scissors" and self.house_choice == "paper"):
            result = "win"
        else:
            result = "lose"
        text = ""
        color = self.ctx.config.colors.approve
        stats = Stats(self.pool)
        if not self.demo:
            if result == "win":
                winnings = int(self.amount * 1.9)
                await self.cache.add_balance(self.user_id, winnings)
                await stats.log_game(self.user_id, "rps", "win", self.amount, winnings)
                text = f"🪨 {interaction.user.mention} won! You earned **{winnings:,}** 💵\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
            elif result == "tie":
                await self.cache.add_balance(self.user_id, self.amount)
                await stats.log_game(self.user_id, "rps", "tie", self.amount)
                text = f"🤝 It's a tie! You got your **{self.amount:,}** 💵 back.\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
            else:
                await stats.log_game(self.user_id, "rps", "lose", self.amount)
                color = self.ctx.config.colors.warn
                text = f"💥 {interaction.user.mention} lost **{self.amount:,}** 💵\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
        else:
            if result == "win":
                text = f"🪨 {interaction.user.mention} won! You earned **0** 💵 (Demo)\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
            elif result == "tie":
                text = f"🤝 It's a tie! You got your **0** 💵 back. (Demo)\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
            else:
                color = self.ctx.config.colors.warn
                text = f"💥 {interaction.user.mention} lost **0** 💵 (Demo)\n\n-# You chose {self.choices[self.choice]} | House chose {self.choices[self.house_choice]}"
        embed = discord.Embed(description=text, color=color)
        await interaction.response.edit_message(embed=embed, view=self)
        await self.redis.delete(f"utils:rps:{self.user_id}:{self.session_id}")

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

async def _rps(ctx: commands.Context, amount: int, pool, redis, bot, cache):
    user = ctx.author
    demo = amount == 0
    session_id = secrets.token_hex(8)
    key = f"utils:rps:{user.id}:{session_id}"
    if not demo:
        balance = await cache.get_balance(user.id)
        if balance < amount:
            await ctx.warn("You don't have enough money for that.", ephemeral=True)
            return
        await cache.subtract_balance(user.id, amount)
        await redis.setex(key, 300, amount)
    color = await bot.get_color(user.id)
    embed = discord.Embed(description="Click a button to make your move against the House", color=color)
    embed.set_footer(text=f"Bet: {amount:,} 💵")
    view = RPSView(ctx, user.id, amount, pool, redis, cache, session_id, demo=demo)
    try:
        message = await ctx.send(embed=embed, view=view)
    except Exception:
        if not demo:
            await cache.add_balance(user.id, amount)
            await redis.delete(key)
        return
    view.message = message
