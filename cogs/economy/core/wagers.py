import discord, secrets
from discord.ext import commands

class PvPRPSButton(discord.ui.Button):
    def __init__(self, emoji: str, choice: str, p1: discord.Member, p2: discord.Member):
        super().__init__(style=discord.ButtonStyle.secondary, emoji=emoji)
        self.choice = choice
        self.p1 = p1
        self.p2 = p2

    async def callback(self, interaction: discord.Interaction):
        v: PvPRPSView = self.view
        await interaction.response.defer()
        if interaction.user.id not in (v.p1.id, v.p2.id):
            await interaction.followup.warn("You're not part of this game!", ephemeral=True)
            return
        if interaction.user.id == v.p1.id:
            if v.p1_choice is not None:
                await interaction.followup.warn("You've already made your choice!", ephemeral=True)
                return
            v.p1_choice = self.choice
        else:
            if v.p2_choice is not None:
                await interaction.followup.warn("You've already made your choice!", ephemeral=True)
                return
            v.p2_choice = self.choice
        await v.update_embed(interaction)

class PvPRPSView(discord.ui.View):
    def __init__(self, ctx, p1, p2, amount, pool, redis, cache, session_id):
        super().__init__(timeout=240)
        self.ctx = ctx
        self.p1 = p1
        self.p2 = p2
        self.amount = amount
        self.pool = pool
        self.redis = redis
        self.cache = cache
        self.session_id = session_id
        self.p1_choice = None
        self.p2_choice = None
        self.game_over = False
        self.add_item(PvPRPSButton("<a:rock:1361492026901925988>", "rock", p1, p2))
        self.add_item(PvPRPSButton("<a:paper:1361492022820733122>", "paper", p1, p2))
        self.add_item(PvPRPSButton("<a:scissors:1361492016894316802>", "scissors", p1, p2))

    async def update_embed(self, interaction):
        if self.p1_choice and self.p2_choice:
            await self.check_winner()
        else:
            if self.p1_choice and not self.p2_choice:
                content = f"{self.p2.mention}"
                desc = f"{self.p1.display_name} locked their choice\n{self.p2.display_name} is choosing..."
            elif self.p2_choice and not self.p1_choice:
                content = f"{self.p1.mention}"
                desc = f"{self.p2.display_name} locked their choice\n{self.p1.display_name} is choosing..."
            else:
                content = f"{self.p1.mention} {self.p2.mention}"
                desc = "-# Click a button to make your move"
            embed = discord.Embed(description=desc, color=await self.ctx.bot.get_color(interaction.user.id))
            await self.message.edit(content=content, embed=embed)

    async def check_winner(self):
        self.game_over = True
        for child in self.children:
            child.disabled = True
        if self.p1_choice == self.p2_choice:
            winner = "tie"
        elif (self.p1_choice == "rock" and self.p2_choice == "scissors") or (self.p1_choice == "paper" and self.p2_choice == "rock") or (self.p1_choice == "scissors" and self.p2_choice == "paper"):
            winner = self.p1
        else:
            winner = self.p2
        emoji_map = {
            "rock": "<a:rock:1361492026901925988>",
            "paper": "<a:paper:1361492022820733122>",
            "scissors": "<a:scissors:1361492016894316802>"
        }
        e1 = emoji_map[self.p1_choice]
        e2 = emoji_map[self.p2_choice]
        if winner == "tie":
            desc = f"**It's a tie!**\n\n-# {self.p1.display_name} chose {e1} & {self.p2.display_name} chose {e2}"
            await self.cache.add_balance(self.p1.id, self.amount)
            await self.cache.add_balance(self.p2.id, self.amount)
            color = self.ctx.config.colors.warn
        else:
            desc = f"**{winner.mention} won ${self.amount*2:,} 💵**\n\n-# {self.p1.display_name} chose {e1} & {self.p2.display_name} chose {e2}"
            await self.cache.add_balance(winner.id, self.amount * 2)
            color = self.ctx.config.colors.approve
        embed = discord.Embed(description=desc, color=color)
        await self.message.edit(embed=embed, view=self)
        await self.redis.delete(f"utils:wager_rps:{self.p1.id}:{self.p2.id}:{self.session_id}")

    async def on_timeout(self):
        if self.game_over:
            return
        self.game_over = True
        for child in self.children:
            child.disabled = True
        await self.cache.add_balance(self.p1.id, self.amount)
        await self.cache.add_balance(self.p2.id, self.amount)
        try:
            await self.message.delete()
        except:
            pass
        await self.redis.delete(f"utils:wager_rps:{self.p1.id}:{self.p2.id}:{self.session_id}")

async def _wager_rps(ctx: commands.Context, amount: int, opponent: discord.User, pool, redis, cache):
    if opponent.bot:
        return await ctx.warn("You can't challenge bots.")
    if opponent.id == ctx.author.id:
        return await ctx.warn("You can't wager yourself.")

    bal1 = await cache.get_balance(ctx.author.id)
    bal2 = await cache.get_balance(opponent.id)

    if bal1 < amount:
        return await ctx.warn("You don't have enough balance to start this wager.")
    if bal2 < amount:
        return await ctx.warn(f"{opponent.display_name} doesn't have enough balance to accept a wager of **${amount:,}**.")

    color = await ctx.bot.get_color(ctx.author.id)
    embed = discord.Embed(
        description=f"🎮 {opponent.mention}, {ctx.author.mention} challenged you to an RPS wager!\n\n💸 **Amount:** ${amount:,}\n⏳ **60 seconds to respond.**",
        color=color
    )

    accept = discord.ui.Button(label="Accept", style=discord.ButtonStyle.success)
    deny = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger)
    view = discord.ui.View(timeout=60)

    session_id = secrets.token_hex(8)
    key = f"utils:wager_rps:{ctx.author.id}:{opponent.id}:{session_id}"

    async def accept_cb(i):
        if i.user.id != opponent.id:
            return await i.response.warn("Not your challenge.", ephemeral=True)

        bal1 = await cache.get_balance(ctx.author.id)
        bal2 = await cache.get_balance(opponent.id)
        if bal1 < amount or bal2 < amount:
            await i.response.warn("One of you doesn't have enough balance anymore.", ephemeral=True)
            await i.message.delete()
            return

        lock = f"wager_lock:{ctx.author.id}:{opponent.id}:{session_id}"
        async with redis.lock(lock, timeout=60):
            bal1 = await cache.get_balance(ctx.author.id)
            bal2 = await cache.get_balance(opponent.id)
            if bal1 < amount or bal2 < amount:
                await i.response.warn("One of you doesn't have enough balance anymore.", ephemeral=True)
                await i.message.delete()
                return

            await cache.subtract_balance(ctx.author.id, amount)
            await cache.subtract_balance(opponent.id, amount)
            await redis.setex(key, 600, amount)

            for x in view.children:
                x.disabled = True
            await i.response.edit_message(view=view)

            embed2 = discord.Embed(description="-# Click a button to make your move", color=color)
            v = PvPRPSView(ctx, ctx.author, opponent, amount, pool, redis, cache, session_id)
            msg2 = await ctx.send(content=f"{ctx.author.mention} {opponent.mention}", embed=embed2, view=v)
            v.message = msg2

    async def deny_cb(i):
        if i.user.id != opponent.id:
            return await i.response.warn("Not your challenge.", ephemeral=True)
        await i.message.delete()

    async def timeout():
        try:
            await msg.delete()
        except:
            pass

    accept.callback = accept_cb
    deny.callback = deny_cb
    view.add_item(accept)
    view.add_item(deny)

    msg = await ctx.send(embed=embed, view=view)
    view.message = msg
    view.on_timeout = timeout