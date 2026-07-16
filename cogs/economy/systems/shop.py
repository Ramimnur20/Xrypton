import time
import io
import discord
from discord.ui import Select, Button, Modal, TextInput
from cogs.economy.ecoutils.framework.pagination import Paginator
from .items import get_shop_items
from cogs.economy.ecoutils.framework.tools.separator import makeseparator

class QuantityModal(Modal):
    def __init__(self, controller, item_id, data):
        super().__init__(title="Purchase Item")
        self.controller = controller
        self.item_id = item_id
        self.data = data
        self.quantity = TextInput(label="Quantity", default="1", min_length=1, max_length=10)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.quantity.value.replace(",", "").strip()
        try:
            qty = int(raw)
            if qty <= 0:
                raise ValueError
        except Exception:
            await interaction.response.warn("Invalid quantity.", ephemeral=True)
            return
        await self.controller.finish_purchase(interaction, self.item_id, self.data, qty)

class ShopController:
    def __init__(self, cog, ctx):
        self.cog = cog
        self.ctx = ctx
        self.user_id = ctx.author.id
        self.current_buttons = []
        self.pages_raw = []
        self.paginator = None

    async def finish_purchase(self, interaction: discord.Interaction, item_id: str, data: dict, qty: int):
        items = get_shop_items()
        if item_id not in items:
            await interaction.response.warn("This item is no longer available.", ephemeral=True)
            return
        item = items[item_id]
        price_total = item["price"] * qty
        lock_key = f"shop_lock:{self.user_id}"
        async with self.cog.redis.lock(lock_key, timeout=5):
            balance = await self.cog.cache.get_balance(self.user_id)
            if balance < price_total:
                await interaction.response.warn(f"You need **${price_total:,}** to buy this.", ephemeral=True)
                return
            await self.cog.cache.subtract_balance(self.user_id, price_total)
            await self.cog.inventory.add_item(self.user_id, item_id, qty)
            left = balance - price_total

        embed = discord.Embed(
            title="Successful Purchase",
            description=f"> You have 💵 **{left:,}** left.\n\n**You bought**:\n* {qty} {item['emoji']} {item['name']}\n\n**You paid**:\n* 💵 **{price_total:,}**"
        )

        if self.paginator and self.pages_raw:
            new_balance = await self.cog.cache.get_balance(self.user_id)
            pages = build_shop_pages(self.cog.bot, new_balance, self.pages_raw)
            self.paginator.pages = pages
            page = self.paginator.pages[self.paginator.index]
            if self.paginator.message:
                await self.paginator.message.edit(embed=page, view=self.paginator)

        await interaction.response.send_message(embed=embed, ephemeral=True)

class ItemButton(Button):
    def __init__(self, controller: ShopController, item_id: str, data: dict):
        emoji = data["emoji"]
        if isinstance(emoji, str) and emoji.startswith("<"):
            emoji = discord.PartialEmoji.from_str(emoji)

        super().__init__(
            label=f"Buy {data['name']}",
            style=discord.ButtonStyle.secondary,
            emoji=emoji
        )

        self.controller = controller
        self.item_id = item_id
        self.data = data

    async def callback(self, interaction: discord.Interaction):
        modal = QuantityModal(self.controller, self.item_id, self.data)
        await interaction.response.send_modal(modal)

class CategorySelect(Select):
    def __init__(self, owner_id: int):
        super().__init__(
            placeholder="Select shop category",
            options=[
                discord.SelectOption(label="Coin Shop", value="coin_shop", emoji="💰", default=True),
                discord.SelectOption(label="Star Shop (soon)", value="star_shop", emoji="⭐", description="Coming soon")
            ]
        )
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.warn("You cannot interact with this menu.", ephemeral=True)
            return
        if self.values[0] == "star_shop":
            await interaction.response.warn("Star Shop is not available yet.", ephemeral=True)
            return
        await interaction.response.defer()

def build_shop_pages(bot, balance: int, pages_raw):
    pages = []
    now = int(time.time())
    ts = (now // 86400 + 1) * 86400
    for chunk in pages_raw:
        lines = []
        lines.append("> Items are always available to purchase.")
        #lines.append(f"> New items will appear at <t:{ts}:t> (<t:{ts}:R>)")
        lines.append(f"-# {bot.config.emojis.context.cash} **{balance:,}**")
        for item_id, data in chunk:
            lines.append(f"### {data['emoji']} {data['name']}\n-# <:pointdrl:1318643571317801040> **${data['price']:,}**")
        embed = discord.Embed(description="\n".join(lines))
        embed.set_author(url=bot.user.display_avatar.url, name="utils Bot Shop")
        embed.set_thumbnail(url="https://git.cursi.ng/utilsbank.png")
        pages.append(embed)
    return pages

async def open_shop(cog, ctx):
    controller = ShopController(cog, ctx)
    shop_items = list(get_shop_items().items())
    if not shop_items:
        embed = discord.Embed(description="No items are available right now.")
        embed.set_author(url=ctx.bot.user.display_avatar.url, name=f"utils Bot Shop")
        await ctx.send(embed=embed)
        return
    pages_raw = []
    for i in range(0, len(shop_items), 6):
        pages_raw.append(shop_items[i:i + 6])
    controller.pages_raw = pages_raw
    balance = await cog.cache.get_balance(controller.user_id)
    pages = build_shop_pages(ctx.bot, balance, pages_raw)

    async def on_page_switch(p: Paginator):
        for btn in list(controller.current_buttons):
            try:
                p.remove_item(btn)
            except:
                pass
        controller.current_buttons.clear()
        idx = p.index
        for item_id, data in controller.pages_raw[idx]:
            btn = ItemButton(controller, item_id, data)
            controller.current_buttons.append(btn)
            p.add_persistent_item(btn)
        page = p.pages[p.index]
        if p.message:
            await p.message.edit(embed=page, view=p)

    paginator = Paginator(ctx, pages, hide_nav=False, hide_footer=True, on_page_switch=on_page_switch, arrows_only=True, only_for_owner=True)
    controller.paginator = paginator
    cat_select = CategorySelect(controller.user_id)
    paginator.add_persistent_item(cat_select)
    for item_id, data in pages_raw[0]:
        btn = ItemButton(controller, item_id, data)
        controller.current_buttons.append(btn)
        paginator.add_persistent_item(btn)
    msg = await paginator.start()
    paginator.message = msg
