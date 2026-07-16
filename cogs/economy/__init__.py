import discord
from discord import app_commands
from discord.ext import commands
from io import BytesIO
from cogs.economy.ecoutils.framework.discord.decorators import check_donor, owner_only, donor_only
from .games.towers import _towers
from .games.mines import _mines
from .games.coinflip import _coinflip
from .games.rps import _rps
from .games.crossroad import _crossroad
from .core.wallet import generate_wallet as wallet
from .core.rewards import claim_daily, claim_bonus, claim_premium_monthly, claim_join_bonus, get_cooldowns
from .core.wagers import _wager_rps
from .core.stats import Stats, StatsView
from .core.cache import Cache
from .core.refund import RefundSystem
from .systems.inventory import InventorySystem
from .systems.shop import open_shop
from .systems.fishing import fish_action
from .systems.items import ITEMS, get_fish_items, get_sellable_items
from cogs.economy.ecoutils.framework.pagination import Paginator
from cogs.economy.ecoutils.framework.discord.commands import CommandCache
from cogs.economy.ecoutils.framework.tools.separator import makeseparator
import io, secrets, os
import importlib, pkgutil, sys, pathlib

SERVER_ID = int(os.getenv("SERVER_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        self.redis = bot.redis
        self.cache = Cache(self.redis, self.pool)
        self.stats = Stats(self.pool)
        self.refund = RefundSystem(self)
        self.inventory = InventorySystem(self.pool)
        self.inventory.attach(self.bot)

    async def cog_load(self):
        base = pathlib.Path(__file__).parent
        prefix = __package__ + "."

        for module in pkgutil.walk_packages([str(base)], prefix=prefix):
            if module.name in sys.modules:
                importlib.reload(sys.modules[module.name])

    async def ensure_wallet(self, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM economy WHERE user_id=$1", user_id)
            if not row:
                await conn.execute("INSERT INTO economy (user_id) VALUES ($1)", user_id)
                row = await conn.fetchrow("SELECT * FROM economy WHERE user_id=$1", user_id)
            return row

    async def _resolve_amount(self, user_id: int, amount: str, source: str):
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow("SELECT money, bank, bank_limit FROM economy WHERE user_id=$1", user_id)
        if not data:
            return None
        amount = amount.lower().replace(",", "").strip()
        if amount == "all":
            return data[source]
        if amount == "half":
            return max(1, data[source] // 2)
        multipliers = {"k": 1000, "m": 1000000, "b": 1000000000}
        try:
            if amount[-1] in multipliers:
                return int(float(amount[:-1]) * multipliers[amount[-1]])
            return int(amount)
        except:
            return None

    async def transfer_funds(self, sender_id: int, receiver_id: int, amount: int):
        if amount <= 0:
            return False, "Amount must be greater than 0."
        lock_sender = f"wallet_lock:{sender_id}"
        lock_receiver = f"wallet_lock:{receiver_id}"
        async with self.redis.lock(lock_sender, timeout=5), self.redis.lock(lock_receiver, timeout=5):
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    sender = await self.ensure_wallet(sender_id)
                    receiver = await self.ensure_wallet(receiver_id)
                    if sender["money"] < amount:
                        return False, "Sender does not have enough money."
                    await conn.execute("UPDATE economy SET money = money - $1 WHERE user_id=$2", amount, sender_id)
                    await conn.execute("UPDATE economy SET money = money + $1 WHERE user_id=$2", amount, receiver_id)
        return True, f"Successfully transferred **${amount:,}** to <@{receiver_id}>."

    async def _atomic_deposit(self, user_id: int, amount: int):
        if amount <= 0:
            return False, "Amount must be greater than 0."
        lock_key = f"wallet_lock:{user_id}"
        async with self.redis.lock(lock_key, timeout=5):
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    data = await conn.fetchrow("SELECT money, bank, bank_limit FROM economy WHERE user_id=$1", user_id)
                    if not data:
                        return False, "Wallet not found."
                    available_money = data["money"]
                    bank_space_left = max(0, data["bank_limit"] - data["bank"])
                    if bank_space_left == 0:
                        return False, "Your bank is already full."
                    deposit_amount = min(amount, available_money, bank_space_left)
                    if deposit_amount <= 0:
                        return False, "Insufficient funds."
                    row = await conn.fetchrow(
                        "UPDATE economy SET money = money - $1, bank = bank + $1 WHERE user_id=$2 RETURNING money, bank, bank_limit",
                        deposit_amount, user_id
                    )
                    return True, f"Deposited **${deposit_amount:,}**. New bank: **${row['bank']:,} / ${row['bank_limit']:,}**."

    async def _atomic_withdraw(self, user_id: int, amount: int):
        if amount <= 0:
            return False, "Amount must be greater than 0."
        lock_key = f"wallet_lock:{user_id}"
        async with self.redis.lock(lock_key, timeout=5):
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "UPDATE economy SET bank = bank - $1, money = money + $1 WHERE user_id=$2 AND bank >= $1 RETURNING money, bank, bank_limit",
                        amount, user_id
                    )
                    if not row:
                        return False, "Not enough in bank to withdraw."
                    return True, f"Withdrew **${amount:,}**. New bank: **${row['bank']:,} / ${row['bank_limit']:,}**."

    @commands.hybrid_group(name="eco", description="Economy commands")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def eco(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @eco.command(name="inventory", description="View your inventory")
    async def eco_inventory(self, ctx: commands.Context):
        await self.inventory.send_inventory(ctx, ctx.author.id)

    @eco.group(name="shop", description="Shop commands")
    async def eco_shop(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @eco_shop.command(name="view", description="View and purchase shop items")
    async def eco_shop_view(self, ctx: commands.Context):
        await open_shop(self, ctx)

    async def shop_item_autocomplete(self, interaction: discord.Interaction, current: str):
        sellable = get_sellable_items()
        inv = await self.inventory.get_inventory(interaction.user.id)
        choices = []
        for item_id, amount in inv.items():
            if item_id in sellable:
                item = sellable[item_id]
                name = item["name"]
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=f"{item['emoji']} {name} ({amount})", value=item_id))
        return choices[:25]

    @eco_shop.command(name="sell", description="Sell an item from your inventory")
    @app_commands.autocomplete(item=shop_item_autocomplete)
    async def eco_shop_sell(self, ctx: commands.Context, item: str, amount: int):
        inv = await self.inventory.get_inventory(ctx.author.id)
        sellable = get_sellable_items()
        if item not in inv:
            return await ctx.warn("You don't have that item.")
        if item not in sellable:
            return await ctx.warn("You cannot sell that item.")
        if amount <= 0:
            return await ctx.warn("Amount must be greater than 0.")
        if inv[item] < amount:
            return await ctx.warn("You don't have that many.")
        data = sellable[item]
        total_value = data["sell_price"] * amount
        color = await self.bot.get_color(ctx.author.id)
        embed = discord.Embed(
            description=f"Are you sure you want to sell **{amount}x** {data['emoji']} **{data['name']}** for {self.bot.config.emojis.context.cash} **${total_value:,}**?",
            color=color
        )
        view = discord.ui.View(timeout=60)
        processed = False

        async def approve_callback(inter: discord.Interaction):
            nonlocal processed
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            if processed:
                return await inter.response.warn("This sale has already been processed.", ephemeral=True)
            processed = True
            current_inv = await self.inventory.get_inventory(ctx.author.id)
            if item not in current_inv or current_inv[item] < amount:
                embed.description = "You don't have that many anymore."
                embed.color = ctx.config.colors.warn
                for child in view.children:
                    child.disabled = True
                view.stop()
                return await inter.response.edit_message(embed=embed, view=view)
            await self.inventory.remove_item(ctx.author.id, item, amount)
            await self.cache.add_balance(ctx.author.id, total_value)
            embed.description = f"Sold {data['emoji']} **{data['name']}** × `{amount}` for **${total_value:,}**."
            embed.color = color
            for child in view.children:
                child.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def deny_callback(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            embed.description = "Cancelled."
            embed.color = ctx.config.colors.warn
            for child in view.children:
                child.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def on_timeout():
            embed.description = "Cancelled (timed out)."
            embed.color = ctx.config.colors.warn
            for child in view.children:
                child.disabled = True
            try:
                await message.edit(embed=embed, view=view)
            except:
                pass

        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
        deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        view.add_item(approve_button)
        view.add_item(deny_button)
        view.on_timeout = on_timeout
        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            message = await ctx.interaction.original_response()
        else:
            message = await ctx.send(embed=embed, view=view)

    @eco.group(name="fish", description="Fishing commands")
    async def eco_fish(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @eco_fish.command(name="catch", description="Go fishing")
    async def eco_fish_catch(self, ctx: commands.Context):
        result = await fish_action(ctx.author.id, self.pool, self.cache, self.inventory)
        if result["status"] == "no_rod":
            ecoshop = await CommandCache.get_mention(self.bot, "eco shop view")
            return await ctx.warn(f"You don't own a **Fishing Rod**. Buy one from the shop with {ecoshop}.")
        if result["status"] == "cooldown":
            ts = result["retry"]
            return await ctx.warn(f"You can go fishing again <t:{ts}:R>.")
        if result["status"] == "stored":
            return await ctx.approve(f"You caught {result['emoji']} **{result['name']}** and stored it in your Fish Bag.")
        if result["status"] == "paid":
            return await ctx.approve(f"You caught {result['emoji']} **{result['name']}** and earned **${result['value']:,}**.\n-# You can store fish in a **Fish Bag** to sell later.")

    @eco_fish.command(name="bag", description="View your fish bag")
    async def eco_fish_bag(self, ctx: commands.Context):
        owns = await self.inventory.has_item(ctx.author.id, "fish_bag")
        if not owns:
            ecoshop = await CommandCache.get_mention(self.bot, "eco shop view")
            return await ctx.warn(f"You don't own a **Fish Bag**. Buy one with {ecoshop}.")

        bag = await self.inventory.get_fishbag(ctx.author.id)
        if not bag:
            return await ctx.warn("Your fish bag is empty.")

        sep_bytes = await makeseparator(self.bot, ctx.author.id)
        sep_file = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
        sep_url = "attachment://separator.png"
        color = await self.bot.get_color(ctx.author.id)

        lines = []
        for fish_id, amount in bag.items():
            f = ITEMS[fish_id]
            lines.append(f"{f['emoji']} **{f['name']}** — `{amount}`")

        chunks = [lines[i:i + 10] for i in range(0, len(lines), 10)]

        if len(chunks) == 1:
            embed = discord.Embed(description="\n".join(chunks[0]), color=color)
            embed.set_author(name=f"{ctx.author.name}'s Fish Bag", icon_url=ctx.author.display_avatar.url)
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            embed.set_image(url=sep_url)
            return await ctx.send(embed=embed, file=sep_file)

        pages = []
        for chunk in chunks:
            embed = discord.Embed(description="\n".join(chunk), color=color)
            embed.set_author(name=f"{ctx.author.name}'s Fish Bag", icon_url=ctx.author.display_avatar.url)
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            embed.set_image(url=sep_url)
            pages.append(embed)

        paginator = Paginator(ctx, pages, hide_nav=False, hide_footer=True, arrows_only=True, only_for_owner=True)
        msg = await paginator.start(file=sep_file)
        paginator.message = msg

    async def fish_autocomplete(self, interaction: discord.Interaction, current: str):
        fishes = get_fish_items()
        bag = await self.inventory.get_fishbag(interaction.user.id)
        choices = []
        for f_id in bag.keys():
            if f_id in fishes:
                fish = fishes[f_id]
                if current.lower() in fish["name"].lower():
                    choices.append(app_commands.Choice(name=f"{fish['emoji']} {fish['name']} ({bag[f_id]})", value=f_id))
        return choices[:25]

    @eco_fish.command(name="sell", description="Sell a specific fish")
    @app_commands.autocomplete(fish=fish_autocomplete)
    async def eco_fish_sell(self, ctx: commands.Context, fish: str, amount: int):
        bag = await self.inventory.get_fishbag(ctx.author.id)
        if fish not in bag:
            return await ctx.warn("You don't have that fish.")
        if amount <= 0:
            return await ctx.warn("Amount must be greater than 0.")
        if bag[fish] < amount:
            return await ctx.warn("You don't have that many.")
        data = ITEMS[fish]
        total_value = data["value"] * amount
        color = await self.bot.get_color(ctx.author.id)
        embed = discord.Embed(
            description=f"Are you sure you want to sell **{amount}x** {data['emoji']} **{data['name']}** for {self.bot.config.emojis.context.cash} **${total_value:,}**?",
            color=color
        )
        view = discord.ui.View(timeout=60)
        processed = False

        async def approve_callback(inter: discord.Interaction):
            nonlocal processed
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            if processed:
                return await inter.response.warn("This sale has already been processed.", ephemeral=True)
            processed = True
            bag_current = await self.inventory.get_fishbag(ctx.author.id)
            if fish not in bag_current or bag_current[fish] < amount:
                embed.description = "You don't have that many anymore."
                embed.color = ctx.config.colors.warn
                for child in view.children:
                    child.disabled = True
                view.stop()
                return await inter.response.edit_message(embed=embed, view=view)
            removed = await self.inventory.remove_fish(ctx.author.id, fish, amount)
            if not removed:
                embed.description = "You don't have that many anymore."
                embed.color = ctx.config.colors.warn
                for child in view.children:
                    child.disabled = True
                view.stop()
                return await inter.response.edit_message(embed=embed, view=view)
            await self.cache.add_balance(ctx.author.id, total_value)
            embed.description = f"Sold {data['emoji']} **{data['name']}** × `{amount}` for **${total_value:,}**."
            embed.color = color
            for child in view.children:
                child.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def deny_callback(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            embed.description = "Cancelled."
            embed.color = ctx.config.colors.warn
            for child in view.children:
                child.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def on_timeout():
            embed.description = "Cancelled (timed out)."
            embed.color = ctx.config.colors.warn
            for child in view.children:
                child.disabled = True
            try:
                await message.edit(embed=embed, view=view)
            except:
                pass

        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
        deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        view.add_item(approve_button)
        view.add_item(deny_button)
        view.on_timeout = on_timeout
        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            message = await ctx.interaction.original_response()
        else:
            message = await ctx.send(embed=embed, view=view)

    @eco.group(name="wager", description="Challenge other players for money")
    async def wager(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @wager.command(name="rps", description="Challenge another player to RPS wager")
    @app_commands.describe(user="The user to challenge", amount="Amount to wager")
    async def wager_rps(self, ctx: commands.Context, user: discord.User, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved <= 0:
            return await ctx.warn("Invalid amount.")
        await _wager_rps(ctx, resolved, user, self.pool, self.redis, self.cache)

    @eco.command(name="wallet", description="View your utils wallet", aliases=["balance", "bal"])
    async def wallet(self, ctx: commands.Context, user: discord.User = None):
        target = user or ctx.author
        data = await self.ensure_wallet(target.id)
        money, bank, bank_limit = data["money"], data["bank"], data["bank_limit"]
        redis_key = f"wallet_embed:{target.id}"
        cached = await self.bot.redis.get(redis_key)
        if cached is not None:
            if isinstance(cached, (bytes, bytearray)):
                cached = cached.decode("utf-8")
            cached = str(cached).strip()
            embed_toggle = cached == "1"
        else:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT embed FROM wallet_settings WHERE user_id=$1", target.id)
            embed_toggle = bool(row["embed"]) if row else False
            await self.bot.redis.set(redis_key, "1" if embed_toggle else "0", ex=86400)
        if embed_toggle:
            color = await self.bot.get_color(target.id)
            sep_bytes = await makeseparator(self.bot, target.id)
            sep = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
            embed = discord.Embed(color=color)
            embed.set_author(name=f"{target.name}'s balance", icon_url=target.display_avatar.url)
            embed.add_field(name=f"{self.bot.config.emojis.context.cash} Money", value=f"${money:,}", inline=True)
            embed.add_field(name="🏦 Bank", value=f"${bank:,} / ${bank_limit:,}", inline=True)
            embed.add_field(name="⭐ Stars", value="0 ⭐", inline=True)
            embed.set_image(url="attachment://separator.png")
            await ctx.send(embed=embed, file=sep)
            return
        buffer = await wallet(self.bot, target, money, bank)
        if buffer is None:
            color = await self.bot.get_color(target.id)
            embed = discord.Embed(color=color)
            embed.set_author(name=f"{target.name}'s balance", icon_url=target.display_avatar.url)
            embed.add_field(name=f"{self.bot.config.emojis.context.cash} Money", value=f"${money:,}", inline=True)
            embed.add_field(name="🏦 Bank", value=f"${bank:,} / ${bank_limit:,}", inline=True)
            embed.add_field(name="⭐ Stars", value="0 ⭐", inline=True)
            await ctx.send(embed=embed)
            return
        await ctx.send(f"> **Viewing wallet card • [**  {target.name} **]**", file=discord.File(buffer, filename="wallet.png"))

    @eco.command(name="transfer", description="Transfer money to someone's wallet", aliases=["pay"])
    @app_commands.describe(user="User to send money to", amount="Amount to send")
    async def transfer(self, ctx: commands.Context, user: discord.User, amount: str):
        sender_id = ctx.author.id
        receiver_id = user.id
        if sender_id == receiver_id:
            return await ctx.warn("You can't transfer money to yourself.")
        resolved = await self._resolve_amount(sender_id, amount, "money")
        if resolved is None or resolved <= 0:
            return await ctx.warn("Invalid amount.")
        success, message = await self.transfer_funds(sender_id, receiver_id, resolved)
        if success:
            await ctx.approve(message)
        else:
            await ctx.warn(message)

    @eco.group(name="bank", description="Banking commands", aliases=["b"])
    async def bank(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @bank.command(name="deposit", description="Deposit money to your bank")
    async def bank_deposit(self, ctx: commands.Context, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved <= 0:
            return await ctx.warn("Invalid amount.")
        success, message = await self._atomic_deposit(ctx.author.id, resolved)
        if success:
            await ctx.approve(message)
        else:
            await ctx.warn(message)

    @bank.command(name="withdraw", description="Withdraw money from your bank")
    async def bank_withdraw(self, ctx: commands.Context, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "bank")
        if resolved is None or resolved <= 0:
            return await ctx.warn("Invalid amount.")
        success, message = await self._atomic_withdraw(ctx.author.id, resolved)
        if success:
            await ctx.approve(message)
        else:
            await ctx.warn(message)

    @bank.command(name="upgrade", description="Upgrade your bank capacity")
    async def bank_upgrade(self, ctx: commands.Context, times: int = 1):
        if times <= 0:
            return await ctx.warn("You must upgrade at least **once**.")
        async with self.pool.acquire() as conn:
            data = await conn.fetchrow("SELECT money, bank_limit FROM economy WHERE user_id=$1", ctx.author.id)
        donor = await check_donor(self.bot, ctx.author.id)
        color = await self.bot.get_color(ctx.author.id)
        current_limit = data["bank_limit"]
        total_increase = (1500 if donor else 1000) * times
        total_cost = int(current_limit * 0.25 * times)
        if data["money"] < total_cost:
            return await ctx.warn(f"You need **${total_cost:,}** to upgrade your bank limit {times}x.")
        new_limit = current_limit + total_increase
        bonus_line = f"\n> {self.bot.config.emojis.context.premium} Premium Bonus Active: +{(1500 - 1000) * times:,} extra capacity gained!" if donor else ""
        embed = discord.Embed(
            description=(
                f"🏦 {ctx.author.mention}, are you sure you want to upgrade your bank?\n\n"
                f"> **Old Limit:** ${current_limit:,}\n"
                f"> **New Limit:** ${new_limit:,}\n"
                f"> **Times Upgraded:** {times}x\n"
                f"> **Total Cost:** {self.bot.config.emojis.context.cash} ${total_cost:,}\n"
                f"> **Total Increase:** +${total_increase:,} {self.bot.config.emojis.context.cash}"
                f"{bonus_line}\n\n"
                f"Click **Approve** to confirm or **Deny** to cancel."
            ),
            color=color
        )
        embed.set_thumbnail(url="https://git.cursi.ng/utilsbank.png")
        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
        deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
        view = discord.ui.View(timeout=15)
        processed = False

        async def approve_callback(inter: discord.Interaction):
            nonlocal processed
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            if processed:
                return await inter.response.warn("This upgrade has already been processed.", ephemeral=True)
            processed = True
            async with self.pool.acquire() as conn:
                current_money = await conn.fetchval("SELECT money FROM economy WHERE user_id=$1", ctx.author.id)
                if current_money < total_cost:
                    embed.description = "Transaction failed — not enough funds."
                    embed.color = ctx.config.colors.warn
                    for item in view.children:
                        item.disabled = True
                    return await inter.response.edit_message(embed=embed, view=view)
                await conn.execute(
                    "UPDATE economy SET money = money - $1, bank_limit = $2 WHERE user_id = $3",
                    total_cost, new_limit, ctx.author.id
                )
            embed.description = (
                f"🏦 {ctx.author.mention}: Bank upgraded successfully!\n\n"
                f"> **Old Limit:** ${current_limit:,}\n"
                f"> **New Limit:** ${new_limit:,}\n"
                f"> **Times Upgraded:** {times}x\n"
                f"> **Total Cost:** ${total_cost:,}\n"
                f"> **Total Increase:** +${total_increase:,} 🏦"
                f"{bonus_line}"
            )
            embed.color = color
            for item in view.children:
                item.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def deny_callback(inter: discord.Interaction):
            if inter.user.id != ctx.author.id:
                return await inter.response.warn("This isn’t your confirmation prompt.", ephemeral=True)
            embed.description = "Cancelled."
            embed.color = ctx.config.colors.warn
            for item in view.children:
                item.disabled = True
            view.stop()
            await inter.response.edit_message(embed=embed, view=view)

        async def on_timeout():
            embed.description = "Cancelled (timed out)."
            embed.color = ctx.config.colors.warn
            for item in view.children:
                item.disabled = True
            try:
                await message.edit(embed=embed, view=view)
            except:
                pass

        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        view.add_item(approve_button)
        view.add_item(deny_button)
        view.on_timeout = on_timeout
        message = await ctx.send(embed=embed, view=view)

    @eco.command(name="towers", description="Bet on Towers")
    @app_commands.describe(amount="The amount to bet")
    async def towers(self, ctx: commands.Context, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved < 0:
            return await ctx.warn("Invalid amount.")
        await _towers(ctx, resolved, self.pool, self.redis, self.bot, self.cache)

    @eco.command(name="mines", description="Bet on Mines")
    @app_commands.describe(amount="The amount to bet", bombs="Number of bombs (1-16)")
    async def mines(self, ctx: commands.Context, amount: str, bombs: int = 3):
        if bombs < 2 or bombs > 16:
            return await ctx.warn("You can only play with **2–16 mines**.")
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved < 0:
            return await ctx.warn("Invalid amount.")
        await _mines(ctx, resolved, bombs, self.pool, self.redis, self.bot, self.cache)

    @eco.command(name="coinflip", description="Bet on Coin Flip", aliases=["cf"])
    @app_commands.describe(amount="The amount to bet", side="The side to bet on (heads/tails/random)")
    @app_commands.choices(side=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
        app_commands.Choice(name="Random", value="random")
    ])
    async def coinflip(self, ctx: commands.Context, amount: str, side: str):
        a = {"h": "heads", "t": "tails", "r": "random"}
        side = a.get(side.lower(), side.lower())
        if side not in ["heads", "tails", "random"]:
            return await ctx.warn("Invalid side. Choose heads, tails, or random.")
        if side == "random":
            side = secrets.choice(["heads", "tails"])
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved < 0:
            return await ctx.warn("Invalid amount.")
        await _coinflip(ctx, resolved, side, self.pool, self.redis, self.bot, self.cache)

    @eco.command(name="rps", description="Bet on RPS", aliases=["rockpaperscissors"])
    @app_commands.describe(amount="The amount to bet")
    async def rps(self, ctx: commands.Context, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved < 0:
            return await ctx.warn("Invalid amount.")
        await _rps(ctx, resolved, self.pool, self.redis, self.bot, self.cache)

    @eco.command(name="crossroad")
    @app_commands.describe(amount="The amount to bet")
    async def crossroad(self, ctx: commands.Context, amount: str):
        resolved = await self._resolve_amount(ctx.author.id, amount, "money")
        if resolved is None or resolved < 0:
            return await ctx.warn("Invalid amount.")
        await _crossroad(ctx, resolved, self.pool, self.redis, self.bot, self.cache)

    @eco.command(name="daily", description="Claim your daily reward")
    async def daily(self, ctx: commands.Context):
        await claim_daily(ctx, self.pool, self.cache, self.bot)

    @eco.command(name="bonus", description="Claim a random bonus reward")
    async def bonus(self, ctx: commands.Context):
        await claim_bonus(ctx, self.pool, self.cache, self.bot)

    @eco.command(name="monthlypremium", description="Claim your monthly Premium cash reward", aliases=["monthly"])
    @donor_only()
    async def monthlypremium(self, ctx: commands.Context):
        if not await check_donor(self.bot, ctx.author.id):
            return await ctx.deny("This is a **Premium** only command.")
        await claim_premium_monthly(ctx, self.pool, self.cache, self.bot)

    @eco.command(name="joinbonus", description="Claim your one-time Join Bonus")
    async def eco_joinbonus(self, ctx: commands.Context):
        await claim_join_bonus(ctx, self.pool, self.cache, self.bot, SERVER_ID)

    @eco.command(name="cooldowns", description="Check your cooldowns", aliases=["cd", "cds", "cooldown"])
    async def cooldowns(self, ctx: commands.Context):
        await get_cooldowns(ctx, self.pool, self.bot)

    @eco.command(name="leaderboard", aliases=["lb"], description="View the richest users on utils")
    async def leaderboard(self, ctx: commands.Context):
        async with self.pool.acquire() as conn:
            data = await conn.fetch("SELECT user_id, money, bank FROM economy ORDER BY (money + bank) DESC LIMIT 100")
        if not data:
            return await ctx.warn("No users found on the leaderboard.")
        sep_bytes = await makeseparator(self.bot, ctx.author.id)
        sep = discord.File(io.BytesIO(sep_bytes), filename="separator.png")
        pages = []
        color = await self.bot.get_color(ctx.author.id)
        total_entries = len(data)
        per_page = 10
        pages_count = (total_entries + per_page - 1) // per_page
        for i in range(pages_count):
            chunk = data[i * per_page:(i + 1) * per_page]
            desc = ""
            for idx, row in enumerate(chunk, start=i * per_page + 1):
                user = self.bot.get_user(row["user_id"])
                name = user.name if user else f"<@{row['user_id']}>"
                total = row["money"] + row["bank"]
                desc += f"**{idx}.** {name} — {self.bot.config.emojis.context.cash} **${total:,}**\n"
            embed = discord.Embed(title="💰 utils Leaderboard", description=desc, color=color)
            embed.set_footer(text=f"Page {i+1}/{pages_count}")
            embed.set_thumbnail(url="https://git.cursi.ng/utilscash.png?v2")
            embed.set_image(url="attachment://separator.png")
            pages.append(embed)
        paginator = Paginator(ctx, pages, hide_footer=True)
        await paginator.start(file=sep)

    @eco.command(name="stats", description="View your game stats")
    async def stats(self, ctx: commands.Context, user: discord.User = None):
        target = user or ctx.author
        has_data = await self.stats.has_stats(target.id)
        embed, sep = await self.stats.build_embed(self.bot, target)
        view = StatsView(self.stats, self.bot, target, ctx.author, disabled=not has_data)
        msg = await ctx.send(embed=embed, view=view, file=sep)
        view.message = msg

async def setup(bot):
    await bot.add_cog(Economy(bot))
