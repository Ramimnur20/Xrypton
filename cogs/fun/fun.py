import ast
import operator
import random
import time
import unicodedata
from decimal import Decimal, getcontext
from datetime import datetime, timedelta
from typing import Optional, Union

import discord
from discord import ButtonStyle, Embed, Member, User
from discord.ext.commands import command
from discord.ui import View

from base.context import Context
from base.managers.types import CogMeta

import aiohttp
from discord import app_commands, Embed, ui
from discord.ext.commands import Cog, hybrid_group
from typing import Optional, Union

from base.config import *


allowed_operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


class SafeMathEvaluator:
    def __init__(self):
        self.start_time = None

    def evaluate_expression(self, expression: str) -> Decimal:
        expression = "".join(c for c in expression if c.isprintable())
        expression = unicodedata.normalize("NFKC", expression)
        if len(expression) > 200:
            raise ValueError("Expression too long")

        getcontext().prec = 50
        self.start_time = time.time()

        tree = ast.parse(expression, mode="eval")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) or isinstance(node, ast.Attribute):
                raise ValueError("Function calls and attribute access are not allowed")
            if isinstance(node, ast.BinOp) and type(node.op) not in allowed_operators:
                raise ValueError("Unsupported operator")
            if isinstance(node, ast.UnaryOp) and type(node.op) not in {
                ast.UAdd,
                ast.USub,
            }:
                raise ValueError("Unsupported unary operator")

        return self._eval_ast(tree.body, 0)

    def _eval_ast(self, node, depth: int) -> Decimal:
        if depth > 20:
            raise ValueError("Maximum recursion depth exceeded")
        if time.time() - self.start_time > 2:
            raise ValueError("Execution time limit exceeded")

        if isinstance(node, ast.BinOp):
            left = self._eval_ast(node.left, depth + 1)
            right = self._eval_ast(node.right, depth + 1)
            op_func = allowed_operators[type(node.op)]

            if isinstance(node.op, ast.Div) and right == 0:
                raise ValueError("Division by zero")

            result = op_func(Decimal(str(left)), Decimal(str(right)))
            if abs(result) > Decimal("1e1000"):
                raise ValueError("Result too large")
            return result

        if isinstance(node, ast.UnaryOp):
            operand = self._eval_ast(node.operand, depth + 1)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand

        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, (int, float)):
                return Decimal(str(value))
            raise ValueError("Unsupported constant")

        raise ValueError("Unsupported expression")


class Fun(CogMeta):
    @command(name="say", description="Make the bot say something.")
    async def say(self, ctx: Context, *, message: str):
        message = message.replace("@", "@\u200B").replace("&", "&\u200B")
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    @command(name="coinflip", aliases=["cf", "coinf"], description="Flip a coin.")
    async def coinflip(self, ctx: Context):
        result = "Heads" if random.choice([True, False]) else "Tails"
        await ctx.send(f"🎲 {result}.")

    @command(name="8ball", description="Consult the 8-ball for an answer.")
    async def eightball(self, ctx: Context, *, question: str):
        answers = [
            "Yes",
            "No",
            "Maybe",
            "Very doubtful",
            "Without a doubt",
            "Most likely",
            "Ask again later",
            "Cannot predict now",
        ]
        await ctx.send(f"🎱 **Question:** {question}\n**Answer:** {random.choice(answers)}")

    @command(name="hotcalc", description="Check how hot someone is.")
    async def hotcalc(
        self, ctx: Context, user: Optional[Union[Member, User]] = None
    ):
        user = user or ctx.author
        hot = random.uniform(0, 100)
        emoji = "💞" if hot > 75 else "💖" if hot > 50 else "❤" if hot > 25 else "💔"
        await ctx.send(f"**{user.name}** is **{hot:.2f}%** hot {emoji}")

    @command(name="howgay", aliases=["gayrate"], description="Check how gay someone is.")
    async def howgay(
        self, ctx: Context, user: Optional[Union[Member, User]] = None
    ):
        user = user or ctx.author
        gay = random.uniform(0, 100)
        emoji = "🏳️‍🌈" if gay > 75 else "🤑" if gay > 50 else "🤫" if gay > 25 else "🔥"
        await ctx.send(f"**{user.name}** is **{gay:.2f}%** gay {emoji}")

    @command(name="ppsize", aliases=["pp"], description="Check the size of someone's pp.")
    async def ppsize(
        self, ctx: Context, user: Optional[Union[Member, User]] = None
    ):
        user = user or ctx.author
        length = random.randint(1, 20)
        pp = "=" * length
        await ctx.send(f"**{user.name}**'s pp:\n**`8{pp}D`**")

    @command(name="rate", description="Rate something.")
    async def rate(self, ctx: Context, *, thing: str):
        lowered = thing.lower()
        if lowered in ["csyn", "cosmin", "heist", "raluca", "hyqos"]:
            rating = 100.0
        elif lowered in ["mihaela", "mira", "yjwe"]:
            rating = -100.0
        else:
            rating = random.uniform(0.0, 100.0)

        await ctx.send(f"I'd rate `{thing}` a **{rating:.2f} / 100**")

    @command(name="math", aliases=["calc", "calculate"], description="Calculate a math expression.")
    async def math(self, ctx: Context, *, expression: str):
        evaluator = SafeMathEvaluator()
        try:
            result = evaluator.evaluate_expression(expression)
        except Exception as exc:
            return await ctx.warn(str(exc))
        await ctx.send(f"`{expression}` = **{result}**")

    @command(name="ship", description="Ship two users together.")
    async def ship(
        self,
        ctx: Context,
        user1: Union[Member, User],
        user2: Optional[Union[Member, User]] = None,
    ):
        user2 = user2 or ctx.author
        love_percent = random.randint(0, 100)
        bar = "❤" * (love_percent // 10)
        await ctx.send(
            embed=Embed(
                title="Ship Result",
                description=(
                    f"{user1.mention} + {user2.mention}\n"
                    f"**Love:** {love_percent}%\n"
                    f"{bar or '💔'}"
                ),
                color=0xF47FFF,
            )
        )

    @command(name="button", description="Create an interactive button.")
    async def button(
        self,
        ctx: Context,
        title: str,
        text: str,
        style: str = "blurple",
        timeout: int = 60,
    ):
        if len(title) > 80:
            return await ctx.warn("Title cannot be longer than 80 characters.")
        if timeout > 240:
            return await ctx.warn("Timeout cannot be longer than 240 seconds.")

        style_map = {
            "blurple": ButtonStyle.primary,
            "green": ButtonStyle.success,
            "grey": ButtonStyle.secondary,
            "red": ButtonStyle.danger,
            "link": ButtonStyle.link,
        }

        btn_style = style_map.get(style.lower())
        if btn_style is None:
            return await ctx.warn("Invalid style. Available: blurple, green, grey, red, link.")

        if btn_style == ButtonStyle.link:
            view = View()
            try:
                view.add_item(
                    discord.ui.Button(label=title, style=btn_style, url=text)
                )
                return await ctx.send(view=view)
            except Exception:
                return await ctx.warn("Invalid URL for link button.")

        class ButtonView(View):
            def __init__(self):
                super().__init__(timeout=timeout)
                button = discord.ui.Button(label=title, style=btn_style)
                button.callback = self.button_callback
                self.add_item(button)

            async def button_callback(
                self, interaction: discord.Interaction
            ):
                await interaction.response.send_message(text, ephemeral=True)

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

        view = ButtonView()
        sent = await ctx.send(view=view)
        view.message = sent

    @command(name="nitro", description="Send a fake Nitro gift.")
    async def nitro(self, ctx: Context):
        expires = datetime.utcnow() + timedelta(hours=24)
        expiration = discord.utils.format_dt(expires, style="R")
        embed = Embed(
            title="You've been gifted a subscription!",
            description=(
                f"You've been gifted Nitro for **1 month**!\n"
                f"Expires {expiration}\n\n[Disclaimer](https://csyn.me/disclaimer)"
            ),
            color=0x7289DA,
        )
        embed.set_thumbnail(url="https://git.cursi.ng/nitro_logo.jpeg")

        class NitroView(View):
            def __init__(self):
                super().__init__(timeout=240)
                button = discord.ui.Button(label="Claim", style=ButtonStyle.blurple)
                button.callback = self.button_callback
                self.add_item(button)

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                return True

            async def button_callback(
                self, interaction: discord.Interaction
            ):
                await interaction.response.send_message(
                    "https://git.cursi.ng/rickroll.gif", ephemeral=True
                )

        view = NitroView()
        sent = await ctx.send(embed=embed, view=view)
        view.message = sent
        view.message = sent



VERB_MAP = {
    "slap": "Slap back",
    "hug": "Hug back",
    "kiss": "Kiss back",
    "bite": "Bite back",
    "baka": "Call baka back",
    "cuddle": "Cuddle back",
    "feed": "Feed back",
    "handhold": "Hold hands back",
    "handshake": "Shake hands back",
    "highfive": "High five back",
    "kick": "Kick back",
    "pat": "Pat back",
    "punch": "Punch back",
    "peck": "Peck back",
    "poke": "Poke back",
    "shoot": "Shoot back",
}

VERB_CONJUGATIONS = {
    "slap": "slaps",
    "hug": "hugs",
    "kiss": "kisses",
    "bite": "bites",
    "baka": "calls baka",
    "cuddle": "cuddles",
    "feed": "feeds",
    "handhold": "holds hands",
    "handshake": "shakes hands",
    "highfive": "high fives",
    "kick": "kicks",
    "pat": "pats",
    "punch": "punches",
    "peck": "pecks",
    "poke": "pokes",
    "shoot": "shoots",
}


class ActionButton(ui.View):
    def __init__(self, action: str, author: discord.Member, target: discord.Member, bot):
        super().__init__(timeout=60)
        self.action = action
        self.author = author
        self.target = target
        self.bot = bot
        self.clicked = False
        self.message: Optional[discord.Message] = None

        button_label = VERB_MAP.get(action, f"{action} back")

        self.button = ui.Button(
            label=button_label,
            style=discord.ButtonStyle.gray,
            emoji=discord.PartialEmoji(name="handsigns", id=1385054141784789133, animated=True),
        )
        self.button.callback = self.callback
        self.add_item(self.button)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                f"Only {self.target.mention} can use this!", ephemeral=True
            )
            return

        if self.clicked:
            await interaction.response.send_message("Already used!", ephemeral=True)
            return

        self.clicked = True
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        cog = self.bot.get_cog("Roleplay")
        ordinal_count = await cog.update_count(self.target.id, self.author.id, self.action)

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://nekos.best/api/v2/{self.action}") as response:
                if response.status == 200:
                    data = await response.json()
                    gif_url = data["results"][0]["url"]
                    anime_name = data["results"][0]["anime_name"]
                else:
                    await interaction.followup.send("Failed to fetch GIF.")
                    return

        conjugated_verb = VERB_CONJUGATIONS.get(self.action, f"{self.action}s")

        embed = Embed(
            description=f"**{self.target.mention}** **{conjugated_verb}** **{self.author.mention}** for the **{ordinal_count}** time!",
            color=COLORS.neutral,
        )
        embed.set_image(url=gif_url)
        embed.set_footer(text=f"From: {anime_name}")

        await interaction.followup.send(embed=embed)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)


class Roleplay(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    async def cog_load(self):
        # user_actions isn't in schema.sql, so we create it here to keep this cog fully drop-in
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS user_actions (
                user_id INTEGER,
                target_user_id INTEGER,
                action TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, target_user_id, action)
            )
            """
        )

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def update_count(self, user_id: int, target_id: int, action: str) -> str:
        try:
            result = await self.bot.pool.fetchrow(
                "SELECT count FROM user_actions WHERE user_id = $1 AND target_user_id = $2 AND action = $3",
                user_id,
                target_id,
                action,
            )

            if result:
                count = result["count"] + 1
                await self.bot.pool.execute(
                    "UPDATE user_actions SET count = $1 WHERE user_id = $2 AND target_user_id = $3 AND action = $4",
                    count,
                    user_id,
                    target_id,
                    action,
                )
            else:
                count = 1
                await self.bot.pool.execute(
                    "INSERT INTO user_actions (user_id, target_user_id, action, count) VALUES ($1, $2, $3, $4)",
                    user_id,
                    target_id,
                    action,
                    count,
                )
        except Exception:
            count = 1

        if 10 <= count % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")

        return f"{count}{suffix}"

    async def send_action_embed(self, ctx, user, action):
        ordinal_count = await self.update_count(ctx.author.id, user.id, action)

        async with self.session.get(f"https://nekos.best/api/v2/{action}") as response:
            if response.status == 200:
                data = await response.json()
                gif_url = data["results"][0]["url"]
                anime_name = data["results"][0]["anime_name"]
            else:
                await ctx.warn(f"Failed to fetch {action} GIF.")
                return

        conjugated_verb = VERB_CONJUGATIONS.get(action, f"{action}s")

        embed = Embed(
            description=f"**{ctx.author.mention}** **{conjugated_verb}** **{user.mention}** for the **{ordinal_count}** time!",
            color=COLORS.neutral,
        )
        embed.set_image(url=gif_url)
        embed.set_footer(text=f"From: {anime_name}")

        if user.id != ctx.author.id:
            view = ActionButton(action, ctx.author, user, self.bot)
            message = await ctx.send(embed=embed, view=view)
            view.message = message
        else:
            await ctx.send(embed=embed)

    @hybrid_group(
        name="roleplay",
        description="Roleplay related commands",
        aliases=["rp"],
        fallback="help",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def roleplay(self, ctx):
        embed = Embed(
            title="Roleplay Commands",
            description="Use these commands to roleplay with other users!",
            color=COLORS.neutral,
        )

        actions = [
            "slap", "hug", "kiss", "bite", "baka", "cuddle", "feed",
            "handhold", "handshake", "highfive", "kick", "pat",
            "punch", "peck", "poke", "shoot", "cry",
        ]

        embed.add_field(
            name="Available Actions",
            value=", ".join(f"`{cmd}`" for cmd in actions),
            inline=False,
        )

        embed.add_field(
            name="Usage",
            value=f"Use `{ctx.prefix}roleplay <action> [@user]` or `/roleplay <action> [user]`",
            inline=False,
        )

        await ctx.send(embed=embed)

    @roleplay.command(name="slap", description="Slap someone")
    @app_commands.describe(user="The user to slap")
    async def slap(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "slap")

    @roleplay.command(name="hug", description="Hug someone")
    @app_commands.describe(user="The user to hug")
    async def hug(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "hug")

    @roleplay.command(name="kiss", description="Kiss someone")
    @app_commands.describe(user="The user to kiss")
    async def kiss(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "kiss")

    @roleplay.command(name="bite", description="Bite someone")
    @app_commands.describe(user="The user to bite")
    async def bite(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "bite")

    @roleplay.command(name="baka", description="Call someone a baka")
    @app_commands.describe(user="The user to call baka")
    async def baka(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "baka")

    @roleplay.command(name="cuddle", description="Cuddle with someone")
    @app_commands.describe(user="The user to cuddle with")
    async def cuddle(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "cuddle")

    @roleplay.command(name="feed", description="Feed someone")
    @app_commands.describe(user="The user to feed")
    async def feed(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "feed")

    @roleplay.command(name="handhold", description="Hold hands with someone")
    @app_commands.describe(user="The user to hold hands with")
    async def handhold(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "handhold")

    @roleplay.command(name="handshake", description="Shake hands with someone")
    @app_commands.describe(user="The user to shake hands with")
    async def handshake(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "handshake")

    @roleplay.command(name="highfive", description="High five someone")
    @app_commands.describe(user="The user to high five")
    async def highfive(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "highfive")

    @roleplay.command(name="kick", description="Kick someone")
    @app_commands.describe(user="The user to kick")
    async def kick(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "kick")

    @roleplay.command(name="pat", description="Pat someone")
    @app_commands.describe(user="The user to pat")
    async def pat(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "pat")

    @roleplay.command(name="punch", description="Punch someone")
    @app_commands.describe(user="The user to punch")
    async def punch(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "punch")

    @roleplay.command(name="peck", description="Peck someone")
    @app_commands.describe(user="The user to peck")
    async def peck(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "peck")

    @roleplay.command(name="poke", description="Poke someone")
    @app_commands.describe(user="The user to poke")
    async def poke(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "poke")

    @roleplay.command(name="shoot", description="Shoot someone")
    @app_commands.describe(user="The user to shoot")
    async def shoot(self, ctx, user: Optional[Union[discord.Member, discord.User]] = None):
        user = user or ctx.author
        await self.send_action_embed(ctx, user, "shoot")

    @roleplay.command(name="cry", description="Let it all out")
    async def cry(self, ctx):
        ordinal_count = await self.update_count(ctx.author.id, ctx.author.id, "cry")

        async with self.session.get("https://nekos.best/api/v2/cry") as response:
            if response.status == 200:
                data = await response.json()
                gif_url = data["results"][0]["url"]
                anime_name = data["results"][0]["anime_name"]
            else:
                await ctx.warn("Failed to fetch cry GIF.")
                return

        embed = Embed(
            description=f"**{ctx.author.mention}** **cries** for the **{ordinal_count}** time!",
            color=COLORS.neutral,
        )
        embed.set_image(url=gif_url)
        embed.set_footer(text=f"From: {anime_name}")

        await ctx.send(embed=embed)