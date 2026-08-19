from base.managers.predicates import example, has_permissions
from typing import Union
from collections import defaultdict
import requests
import io
import time
import aiohttp
# import shazamio
# from shazamio import Shazam, Serialize
import re
from re import match

from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice
from humanize import naturaltime
import humanize
from datetime import datetime
import time
from base.managers.EmbedBuilder import *
from discord.ui import Button, View
from discord import ButtonStyle
from discord.ui import View, Button, Modal, TextInput


from discord import (
    Embed,
    User,
    Member,
    Message,
    Spotify,
    ActivityType,
    Permissions,
    Status,
    Invite,
    Role,
    Button,
    ButtonStyle,
)
from discord.app_commands import (
    allowed_installs,
    allowed_contexts,
)
from discord.ext.commands import (
    command,
    cooldown,
    BucketType,
    Author,
    command,
    hybrid_group,
    group,
    Cog,
)

from base.managers.types import CogMeta
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url
from datetime import datetime, timedelta
import asyncio
from psutil import Process


class Miscellaneous(CogMeta):
    embed_builder = EmbedBuilder
    embed_script = "{embed}"

    @example(",afk busy")
    @command(name="afk", description="Display your AFK message.")
    async def afk(self, ctx: Context, *, reason: str = "AFK") -> Message:
        current_time = int(datetime.now().timestamp())
        await self.bot.pool.execute(
            "INSERT INTO afk (user_id, time, status) VALUES ($1, $2, $3)",
            ctx.author.id,
            current_time,
            reason,
        )
        return await ctx.approve(f"You have gone **AFK** with status:  **{reason}**")

    @Cog.listener("on_message")
    async def afk_listener(self, message: Message):
        if message.author == self.bot.user:
            return

        db = await self.bot.pool.fetchrow(
            "SELECT prefix FROM prefix WHERE guild_id = $1", message.guild.id
        )  # type: ignore
        prefix = db["prefix"] if db else ","

        if message.content.strip().startswith(prefix + "afk"):
            return

        afk_data = await self.bot.pool.fetchrow(
            "SELECT status, time FROM afk WHERE user_id = $1", message.author.id
        )
        if afk_data:
            status, start_time = afk_data["status"], afk_data["time"]
            start_time = datetime.fromtimestamp(start_time)
            now = datetime.now()
            time_away = humanize.naturaldelta(now - start_time)

            await self.bot.pool.execute(
                "DELETE FROM afk WHERE user_id = $1", message.author.id
            )

            embed = Embed(
                description=f"👋 {message.author.mention}: Welcome back, you were away for **{time_away}**"
            )
            await message.channel.send(embed=embed)

        if message.mentions:
            for user in message.mentions:
                afk_data = await self.bot.pool.fetchrow(
                    "SELECT status, time FROM afk WHERE user_id = $1", user.id
                )
                if afk_data:
                    status, start_time = afk_data["status"], afk_data["time"]
                    start_time = datetime.fromtimestamp(start_time)
                    now = datetime.now()
                    time_away = humanize.naturaldelta(now - start_time)

                    embed = Embed(
                        description=f"💤 {user.mention}: is AFK: **{status}** - **{time_away}**"
                    )
                    await message.channel.send(embed=embed)

    @example(",urban xrypton")
    @command(
        name="urban",
        aliases=["urbandictionary"],
        description="Lookup a word on urban dictonary",
    )
    async def urban(self, ctx: Context, *, word: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://api.urbandictionary.com/v0/define?term={word}"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    definitions = data.get("list", [])
                    embeds = []

                    total_entries = len(definitions)
                    total_pages = total_entries + 1 - 1

                    for definition in definitions:
                        embed = discord.Embed(
                            title=f"{word}",
                            description=definition.get(
                                "definition", "No definition found."
                            ),
                            color=COLORS.neutral,
                        )
                        embed.add_field(
                            name="Example",
                            value=definition.get("example", "No example found."),
                            inline=False,
                        )
                        embed.set_footer(
                            text=f"👍 {definition.get('thumbs_up', 0)} • 👎 {definition.get('thumbs_down', 0)} • entries: {total_entries}"
                        )
                        embeds.append(embed)

                    await ctx.paginate(embeds)
                else:
                    await ctx.warn("Failed to retrieve data from Urban Dictionary.")

    @example(",quickpoll")
    @command(name="quickpoll", aliases=["qp"], description="Create a quick poll")
    async def quickpoll(self, ctx: Context):
        await ctx.message.add_reaction("⬆️")
        await ctx.message.add_reaction("⬇️")

    # @command(name="shazam", description="Get a song from a video")
    # async def shazam(self, ctx: Context):
    #     if ctx.message.reference:
    #         ref_message = await ctx.channel.fetch_message(
    #             ctx.message.reference.message_id  # type: ignore
    #         )
    #         if ref_message.attachments:
    #             attachment = ref_message.attachments[0]
    #         else:
    #             await ctx.warn(
    #                 "The replied-to message does not contain a video or audio file."
    #             )
    #             return
    #     elif ctx.message.attachments:
    #         attachment = ctx.message.attachments[0]
    #     else:
    #         await ctx.warn("Please provide a video or audio file.")
    #         return
    #     if not (
    #         attachment.content_type.startswith("audio/")  # type: ignore
    #         or attachment.content_type.startswith("video/")  # type: ignore
    #     ):
    #         await ctx.warn("The provided file is not an audio or video file.")
    #         return

    #     async with ctx.typing():
    #         audio_data = await attachment.read()
    #         shazam = Shazam()

    #         try:
    #             song = await shazam.recognize(audio_data)
    #             if "track" not in song or "share" not in song["track"]:
    #                 return await ctx.send("Could not recognize the track.")

    #             song_cover_url = song["track"]["images"].get("coverart", "")
    #             return await ctx.embed(
    #                 description=f"{EMOJIS.SHAZAM} {ctx.author.mention}: Found **[{song['track']['share']['text']}]({song['track']['share']['href']})**",
    #                 color=0x38A9E1,
    #             )

    #         except Exception as E:
    #             return await ctx.warn(f"An error occurred: **{E}**")

    # command above was commented because im bored for shazamio-core to build but i hope its functional when it does build.
    @example(",createembed {embed}$v{title:Hello}$v{description:World}")
    @hybrid_group(
        name="embed",
        aliases=["embeds"],
        invoke_without_command=True,
        description="Create and manage custom embeds.",
    )
    @has_permissions(manage_messages=True)
    async def embed(self, ctx: Context, *, script: EmbedScript = None) -> Message:
        if script is None:
            return await ctx.send_help(ctx.command)
        return await ctx.send(**script)

    @embed.command(
        name="create",
        aliases=["add", "send", "build", "script", "embedcreate"],
        description="Create an embed from a script.",
    )
    @has_permissions(manage_messages=True)
    async def embed_create(self, ctx: Context, *, script: EmbedScript = None) -> Message:
        if script is None:
            return await ctx.warn(
                "Enter an embed script. Visually build one at <https://xrypton.bot/embed.html> or run `,help createembed`."
            )
        return await ctx.send(**script)

    @embed.command(
        name="code",
        aliases=["get", "copy"],
        description="Get embed code from a message url.",
    )
    @has_permissions(manage_messages=True)
    async def embed_code(self, ctx: Context, message_link: str):
        return await self.embedcode(ctx, message_link=message_link)

    @embed.command(
        name="builder",
        aliases=["web", "link"],
        description="Get the link to the visual embed builder.",
    )
    async def embed_builder_link(self, ctx: Context):
        return await ctx.embed(
            title="Xrypton Embed Builder",
            description="Visually build embeds and generate embed scripts for `,createembed`.\n\n🔗 **[Open Embed Builder](https://xrypton.bot/embed.html)**",
        )

    @example(",createembed {embed}$v{title:Hello}$v{description:World}")
    @command(
        name="createembed",
        aliases=["ce", "script", "embedcreate"],
        description="Create an embed.",
    )
    @has_permissions(manage_messages=True)
    async def createembed(self, ctx: Context, *, script: EmbedScript = None) -> Message:  # type: ignore
        if script is None:
            return await ctx.warn(
                "Enter an embed script. Visually build one at <https://xrypton.bot/embed.html> or run `,help createembed`."
            )
        return await ctx.send(**script)  # type: ignore

    @example(",embedcode https://discord.com/channels/123/456/789")
    @command(
        name="embedcode",
        aliases=["ec"],
        description="Get embed code from a message url",
    )
    async def embedcode(self, ctx: Context, message_link: str):
        try:
            if message_link.strip().lower().startswith(("{embed}", "$v", "{content:", "{title:", "{description:")):
                return await ctx.warn(
                    "It looks like you entered an embed script! Use **,ce** or **,createembed** to send it.\n"
                    "**,ec** is short for **embedcode** (used to copy an embed from a message link)."
                )

            match_res = re.search(r"channels/(\d+)/(\d+)/(\d+)", message_link)
            if not match_res:
                return await ctx.warn(
                    "Invalid message link. Format: `https://discord.com/channels/<guild_id>/<channel_id>/<message_id>`"
                )

            guild_id, channel_id, message_id = map(int, match_res.groups())

            guild = ctx.bot.get_guild(guild_id)
            if not guild:
                return await ctx.warn("I cannot access that guild.")

            channel = guild.get_channel(channel_id)
            if not channel:
                return await ctx.warn("I cannot access that channel.")

            try:
                message = await channel.fetch_message(message_id)  # type: ignore
            except discord.NotFound:
                return await ctx.deny("Message not found.")
            except discord.Forbidden:
                return await ctx.deny("I don't have permission to view that message.")

            if not message.embeds:
                return await ctx.warn(
                    "The specified message does not contain an embed."
                )

            embed = message.embeds[0]
            parts = ["{embed}"]

            if message.content:
                parts.append(f"$v{{content:{message.content}}}")

            if embed.title:
                parts.append(f"$v{{title:{embed.title}}}")

            if embed.description:
                parts.append(f"$v{{description:{embed.description}}}")

            if embed.color:
                parts.append(f"$v{{color:{hex(embed.color.value)[2:]}}}")

            if embed.author and embed.author.name:
                author_parts = [
                    embed.author.name or "",
                    embed.author.icon_url or "",
                    embed.author.url or "",
                ]
                parts.append(f"$v{{author:{' && '.join(author_parts)}}}")

            for field in embed.fields:
                parts.append(
                    f"$v{{field:{field.name} && {field.value} && {str(field.inline).lower()}}}"
                )

            if embed.footer and embed.footer.text:
                footer_parts = [embed.footer.text or "", embed.footer.icon_url or ""]
                parts.append(f"$v{{footer:{' && '.join(footer_parts)}}}")

            if embed.image and embed.image.url:
                parts.append(f"$v{{image:{embed.image.url}}}")

            if embed.thumbnail and embed.thumbnail.url:
                parts.append(f"$v{{thumbnail:{embed.thumbnail.url}}}")

            if message.components:
                for row in message.components:
                    for button in row.children:
                        if isinstance(button, discord.Button):
                            btn_parts = []
                            if button.label:
                                btn_parts.append(f"label:{button.label}")
                            if button.emoji:
                                btn_parts.append(f"emoji:{button.emoji}")
                            if getattr(button, "url", None):
                                btn_parts.append(f"url:{button.url}")
                            if button.style and button.style != discord.ButtonStyle.link:
                                btn_parts.append(f"style:{button.style.name.lower()}")
                            if button.disabled:
                                btn_parts.append("disabled")
                            if btn_parts:
                                parts.append(f"$v{{button:{' && '.join(btn_parts)}}}")

            embed_script = "\n".join(parts)
            await ctx.embed(
                description=f"{EMOJIS.APPROVE} {ctx.author.mention}: **Copied embed script: **```\n{embed_script}\n```",
                buttons=[{"label": "Code", "emoji": "🔗"}],
            )

        except Exception as e:
            await ctx.warn(f"An error occurred: {str(e)}")

    @example(",pin")
    @command(name="pin", description="Pin a message.")
    @has_permissions(manage_messages=True)
    async def pin(self, ctx: Context, *, message: str = None):
        message = None

        if ctx.message.reference:
            message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        elif message:
            match = match(r"https://discord.com/channels/(\d+)/(\d+)/(\d+)", message)
            if match:
                guild_id, channel_id, message_id = map(int, match.groups())
                if guild_id == ctx.guild.id:
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        message = await channel.fetch_message(message_id)

        if message:
            await message.pin()
            return await ctx.message.add_reaction("📌")

    @example(",unpin")
    @command(name="unpin", description="Unpin a message.")
    @has_permissions(manage_messages=True)
    async def unpin(self, ctx: Context, *, message: str = None):
        message = None

        if ctx.message.reference:
            message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        elif message:
            match = match(r"https://discord.com/channels/(\d+)/(\d+)/(\d+)", message)
            if match:
                guild_id, channel_id, message_id = map(int, match.groups())
                if guild_id == ctx.guild.id:
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        message = await channel.fetch_message(message_id)

        if message:
            await message.unpin()
            return await ctx.message.add_reaction("📌")

    @example(",donate")
    @command(name="donate", description="Learn why Xrypton doesn't take donations.")
    async def donate(self, ctx: Context):
        return await ctx.embed(
            title="Why Xrypton Doesn't Take Donations",
            description="""
💡 **Made for fun**: Xrypton exists because I enjoy creating bots and experimenting with Discord's quirks. It's something I do for the love of it, not for profit.
🛑 **No strings attached**: Donations often create expectations — faster updates, special features, or personal support. I'd rather keep Xrypton free of obligations so it can grow naturally.
🌍 **Free means free**: Bots should be accessible to everyone without guilt or paywalls. You don't need to spend a dime to enjoy Xrypton.
🙅 **Not a business**: I don't want Xrypton to turn into a commercial product. Keeping it donation‑free ensures it stays playful, community‑driven, and true to its purpose.
**How to support Xrypton**: The best way is to **use it, share it, and help improve it** — whether that's reporting bugs, suggesting features, or spreading the word.
            """,
            author={"name": ctx.author.name, "icon_url": ctx.author.display_avatar.url},
            thumbnail=self.bot.user.avatar.url,
        )

    @example(",suggest add a new command")
    @command(
        name="suggest",
        aliases=["suggestion"],
        description="Suggest a feature for the developers to add.",
    )
    async def suggest(self, ctx: Context, *, suggestion: str):
        embed = Embed(title=f"New suggestion", description=suggestion)
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
        channel = self.bot.get_channel(1527307333858754742) or await self.bot.fetch_channel(1527307333858754742)
        await channel.send(embed=embed, content="<@1470775670262202590>")
        ctx.approve("successfully sent your suggestion to the developers.")

import discord
from discord import app_commands
from discord.ext import commands

from typing import Optional


class Customize(CogMeta):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    FONTS: dict[int, str] = {
        1: "Bold Comic",
        2: "Elegant Serif",
        3: "Sakura",
        4: "Jellybean",
        5: "Display",
        6: "Modern",
        7: "Medieval",
        8: "8Bit",
        9: "Decorative",
        10: "Vampyre",
        11: "Default",
        12: "Tempo",
    }

    EFFECTS: dict[int, dict] = {
        1: {"label": "Solid", "colors_required": 1, "colors_max": 1},
        2: {"label": "Gradient", "colors_required": 2, "colors_max": 2},
        3: {"label": "Neon", "colors_required": 1, "colors_max": 1},
        4: {"label": "Toon", "colors_required": 1, "colors_max": 1},
        5: {"label": "Pop", "colors_required": 1, "colors_max": 1},
        6: {"label": "Glow", "colors_required": 1, "colors_max": 2},
    }

    async def cog_load(self) -> None:
        await self._init_db()
        for column in [
            "namestyle_font_id",
            "namestyle_effect_id",
            "namestyle_color1",
            "namestyle_color2",
        ]:
            try:
                await self.bot.pool.execute(
                    f"ALTER TABLE bot_customizations ADD COLUMN {column} INTEGER"
                )
            except Exception:
                pass

    async def _init_db(self) -> None:
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_customizations (
                guild_id INTEGER PRIMARY KEY,
                custom_name TEXT,
                custom_avatar_url TEXT,
                custom_banner_url TEXT,
                custom_bio TEXT,
                namestyle_font_id INTEGER,
                namestyle_effect_id INTEGER,
                namestyle_color1 INTEGER,
                namestyle_color2 INTEGER
            )
            """
        )

    async def _get_custom(self, guild_id: int) -> dict:
        row = await self.bot.pool.fetchrow(
            "SELECT * FROM bot_customizations WHERE guild_id = $1", guild_id
        )
        return dict(row) if row else {}

    async def _set_custom(self, guild_id: int, **kwargs) -> None:
        if not kwargs:
            return

        keys = list(kwargs.keys())
        values = [guild_id] + list(kwargs.values())
        col_list = ", ".join(keys)
        placeholders = ", ".join(f"${i + 2}" for i in range(len(keys)))
        set_clause = ", ".join(f"{k} = excluded.{k}" for k in keys)

        query = f"""
            INSERT INTO bot_customizations (guild_id, {col_list})
            VALUES ($1, {placeholders})
            ON CONFLICT(guild_id) DO UPDATE SET {set_clause}
        """
        await self.bot.pool.execute(query, *values)

    async def _clear_field(self, guild_id: int, field: str) -> None:
        await self.bot.pool.execute(
            f"UPDATE bot_customizations SET {field} = NULL WHERE guild_id = $1",
            guild_id,
        )

    async def _reset_all(self, guild_id: int) -> None:
        await self.bot.pool.execute(
            "DELETE FROM bot_customizations WHERE guild_id = $1", guild_id
        )

    async def _apply_namestyle(self, guild_id: int) -> None:
        data = await self._get_custom(guild_id)
        font_id = data.get("namestyle_font_id")
        effect_id = data.get("namestyle_effect_id")
        color1 = data.get("namestyle_color1")
        color2 = data.get("namestyle_color2")

        if color1 is not None:
            colors = [color1] if color2 is None else [color1, color2]
        else:
            colors = [16777215]

        payload = {
            "display_name_font_id": font_id if font_id is not None else 11,
            "display_name_effect_id": effect_id if effect_id is not None else 1,
            "display_name_colors": colors,
        }

        import aiohttp
        url = f"https://discord.com/api/v10/guilds/{guild_id}/members/@me"
        headers = {
            "Authorization": f"Bot {self.bot.http.token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, json=payload, headers=headers) as resp:
                if resp.status not in (200, 204):
                    text = await resp.text()
                    raise RuntimeError(f"HTTP {resp.status}: {text}")

    async def _download_image(self, url: str) -> bytes:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
                raise ValueError(f"Failed to download image: HTTP {resp.status}")

    async def cog_unload(self) -> None:
        for guild in self.bot.guilds:
            try:
                await guild.me.edit(nick=None, avatar=None, banner=None, bio=None)
            except RuntimeError:
                pass
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await self._clear_field(guild.id, 'namestyle_font_id')
                await self._clear_field(guild.id, 'namestyle_effect_id')
                await self._clear_field(guild.id, 'namestyle_color1')
                await self._clear_field(guild.id, 'namestyle_color2')
                await self._apply_namestyle(guild.id)
            except RuntimeError:
                pass
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return True

        perms = ctx.author.guild_permissions
        if not (perms.manage_guild or perms.administrator):
            raise commands.MissingPermissions(["manage_guild", "administrator"])
        return True

    @example(",customize")
    @hybrid_group(name="customize", invoke_without_command=True)
    async def customize(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        data = await self._get_custom(ctx.guild.id)
        embed = discord.Embed(
            title="Server Customizations",
            description="View or modify how Xrypton appears in this server.",
            color=discord.Color.blurple(),
        )
        for field, label in [
            ("custom_name", "Nickname"),
            ("custom_avatar_url", "Avatar"),
            ("custom_banner_url", "Banner"),
            ("custom_bio", "Bio"),
        ]:
            value = data.get(field) or "None"
            embed.add_field(name=label, value=value, inline=False)
        font_id = data.get("namestyle_font_id")
        effect_id = data.get("namestyle_effect_id")
        color1 = data.get("namestyle_color1")
        color2 = data.get("namestyle_color2")
        font_label = self.FONTS.get(font_id, "None") if font_id else "None"
        effect_label = self.EFFECTS.get(effect_id, {}).get("label", "None") if effect_id else "None"
        if color1 is not None:
            color_str = f"#{color1:06X}"
            if color2 is not None:
                color_str += f" / #{color2:06X}"
        else:
            color_str = "None"
        embed.add_field(name="Font", value=font_label, inline=True)
        embed.add_field(name="Effect", value=effect_label, inline=True)
        embed.add_field(name="Colours", value=color_str, inline=True)
        embed.add_field(
            name="Commands",
            value=(
                "`customize avatar`, `customize name`, `customize banner`, "
                "`customize aboutme`, `customize reset`, `customize resetall`, "
                "`customize namestyle font/colour/effect`"
            ),
            inline=False,
        )
        await ctx.reply(embed=embed, mention_author=False)

    @customize.command(name="avatar", description="Set a new avatar for the bot in this server")
    @app_commands.describe(url="Direct image URL for the avatar")
    async def avatar(
        self, ctx: commands.Context, attachment: Optional[discord.Attachment] = None, url: Optional[str] = None
    ) -> None:
        if not ctx.guild:
            return

        media_url = None
        if attachment and attachment.content_type and attachment.content_type.startswith("image/"):
            media_url = attachment.url
        elif url:
            media_url = url.strip()

        if not media_url:
            return await ctx.reply("Provide a valid image attachment or URL.", mention_author=False)

        try:
            img_bytes = await self._download_image(media_url)
        except Exception as e:
            return await ctx.warn(f"Failed to fetch image: `{e}`")

        await self._set_custom(ctx.guild.id, custom_avatar_url=media_url)
        try:
            await ctx.guild.me.edit(avatar=img_bytes)
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update avatar: `{e}`")

        await ctx.reply("Avatar updated for this server.", mention_author=False)

    @customize.command(name="name", description="Set a new nickname for the bot in this server")
    @app_commands.describe(name="New nickname for the bot")
    async def name(self, ctx: commands.Context, name: str) -> None:
        if not ctx.guild:
            return

        try:
            await ctx.guild.me.edit(nick=name)
        except discord.Forbidden:
            return await ctx.reply("I don't have permission to change my nickname.", mention_author=False)

        await self._set_custom(ctx.guild.id, custom_name=name)
        await ctx.reply(f"Nickname updated to **{name}**.", mention_author=False)

    @customize.command(name="banner", description="Set a new banner for the bot in this server")
    @app_commands.describe(url="Direct image URL for the banner")
    async def banner(
        self, ctx: commands.Context, attachment: Optional[discord.Attachment] = None, url: Optional[str] = None
    ) -> None:
        if not ctx.guild:
            return

        media_url = None
        if attachment and attachment.content_type and attachment.content_type.startswith("image/"):
            media_url = attachment.url
        elif url:
            media_url = url.strip()

        if not media_url:
            return await ctx.reply("Provide a valid image attachment or URL.", mention_author=False)

        try:
            img_bytes = await self._download_image(media_url)
        except Exception as e:
            return await ctx.warn(f"Failed to fetch image: `{e}`")

        await self._set_custom(ctx.guild.id, custom_banner_url=media_url)
        try:
            await ctx.guild.me.edit(banner=img_bytes)
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update banner: `{e}`")

        await ctx.reply("Banner updated for this server.", mention_author=False)

    @customize.command(name="aboutme", description="Set a new bio for the bot in this server")
    @app_commands.describe(bio="New bio for the bot's server profile")
    async def aboutme(self, ctx: commands.Context, *, bio: str) -> None:
        if not ctx.guild:
            return

        await self._set_custom(ctx.guild.id, custom_bio=bio)
        try:
            await ctx.guild.me.edit(bio=bio)
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update bio: `{e}`")

        await ctx.reply("Bio updated for this server.", mention_author=False)

    @customize.command(name="reset", description="Reset a specific customization for this server")
    @app_commands.choices(field=[
        app_commands.Choice(name="avatar", value="avatar"),
        app_commands.Choice(name="name", value="name"),
        app_commands.Choice(name="banner", value="banner"),
        app_commands.Choice(name="aboutme", value="aboutme"),
        app_commands.Choice(name="namestyle", value="namestyle"),
    ])
    @app_commands.describe(field="Which customization to reset")
    async def reset(self, ctx: commands.Context, field: str) -> None:
        if not ctx.guild:
            return

        mapping = {
            "avatar": "custom_avatar_url",
            "name": "custom_name",
            "banner": "custom_banner_url",
            "aboutme": "custom_bio",
            "namestyle": None,
        }
        if field == "namestyle":
            await self._clear_field(ctx.guild.id, "namestyle_font_id")
            await self._clear_field(ctx.guild.id, "namestyle_effect_id")
            await self._clear_field(ctx.guild.id, "namestyle_color1")
            await self._clear_field(ctx.guild.id, "namestyle_color2")
            me = ctx.guild.me
            try:
                from discord.http import Route
                route = Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=ctx.guild.id)
                await self.bot.http.request(route, json={
                    "display_name_font_id": None,
                    "display_name_effect_id": None,
                    "display_name_colors": None,
                })
            except (discord.Forbidden, discord.HTTPException) as e:
                return await ctx.warn(f"Failed to reset namestyle: `{e}`")
            return await ctx.reply("Reset **namestyle** to default.", mention_author=False)

        db_field = mapping.get(field)
        if not db_field:
            return await ctx.reply("Invalid field. Choose from avatar, name, banner, aboutme, namestyle.", mention_author=False)

        await self._clear_field(ctx.guild.id, db_field)
        me = ctx.guild.me

        try:
            if field == "avatar":
                await me.edit(avatar=None)
            elif field == "name":
                await me.edit(nick=None)
            elif field == "banner":
                await me.edit(banner=None)
            elif field == "aboutme":
                await me.edit(bio=None)
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to reset {field}: `{e}`")

        await ctx.reply(f"Reset **{field}** to default.", mention_author=False)

    @customize.command(name="resetall", description="Reset all customizations for this server")
    async def resetall(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        me = ctx.guild.me
        try:
            await me.edit(nick=None, avatar=None, banner=None, bio=None)
        except (discord.Forbidden, discord.HTTPException) as e:
            await ctx.warn(f"Failed to reset customizations: `{e}`")

        await self._clear_field(ctx.guild.id, "namestyle_font_id")
        await self._clear_field(ctx.guild.id, "namestyle_effect_id")
        await self._clear_field(ctx.guild.id, "namestyle_color1")
        await self._clear_field(ctx.guild.id, "namestyle_color2")
        try:
            await self._apply_namestyle(ctx.guild.id)
        except RuntimeError as e:
            await ctx.warn(str(e))
        except (discord.Forbidden, discord.HTTPException):
            pass

        await self._reset_all(ctx.guild.id)
        await ctx.reply("All customizations have been reset.", mention_author=False)


    @customize.group(name="namestyle", invoke_without_command=True, description="Configure the bot's name style")
    async def namestyle(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return

        data = await self._get_custom(ctx.guild.id)
        font_id = data.get("namestyle_font_id")
        effect_id = data.get("namestyle_effect_id")
        color1 = data.get("namestyle_color1")
        color2 = data.get("namestyle_color2")

        font_label = self.FONTS.get(font_id, "None") if font_id else "None"
        effect_label = self.EFFECTS.get(effect_id, {}).get("label", "None") if effect_id else "None"
        if color1 is not None:
            color_str = f"#{color1:06X}"
            if color2 is not None:
                color_str += f" / #{color2:06X}"
        else:
            color_str = "None"

        embed = discord.Embed(
            title="Namestyle Configuration",
            description=f"Font: **{font_label}**\nEffect: **{effect_label}**\nColours: **{color_str}**",
            color=discord.Color.blurple(),
        )
        await ctx.reply(embed=embed, mention_author=False)

    @namestyle.command(name="font", description="Set the bot's name font")
    @app_commands.choices(font=[
        app_commands.Choice(name="Bold Comic", value="1"),
        app_commands.Choice(name="Elegant Serif", value="2"),
        app_commands.Choice(name="Sakura", value="3"),
        app_commands.Choice(name="Jellybean", value="4"),
        app_commands.Choice(name="Display", value="5"),
        app_commands.Choice(name="Modern", value="6"),
        app_commands.Choice(name="Medieval", value="7"),
        app_commands.Choice(name="8Bit", value="8"),
        app_commands.Choice(name="Decorative", value="9"),
        app_commands.Choice(name="Vampyre", value="10"),
        app_commands.Choice(name="Default", value="11"),
        app_commands.Choice(name="Tempo", value="12"),
    ])
    @app_commands.describe(font="The font to use for the bot's name")
    async def font(self, ctx: commands.Context, font: str) -> None:
        if not ctx.guild:
            return

        font_id = None
        font_label = None
        if font.isdigit():
            fid = int(font)
            if fid in self.FONTS:
                font_id = fid
                font_label = self.FONTS[fid]
            else:
                return await ctx.warn(f"Invalid font ID. Choose from: {', '.join(self.FONTS.values())}")
        else:
            for fid, label in self.FONTS.items():
                if label.lower() == font.lower():
                    font_id = fid
                    font_label = label
                    break
            if font_id is None:
                return await ctx.warn(f"Invalid font. Choose from: {', '.join(self.FONTS.values())}")

        await self._set_custom(ctx.guild.id, namestyle_font_id=font_id)
        try:
            await self._apply_namestyle(ctx.guild.id)
        except RuntimeError as e:
            return await ctx.warn(str(e))
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update namestyle font: `{e}`")

        await ctx.approve(f"Namestyle font updated to **{font_label}**.", mention_author=False)

    @namestyle.command(name="colour", aliases=["color"], description="Set the bot's name colours")
    @app_commands.describe(colour1="Primary colour (hex, e.g. #FF0000 or FF0000)", colour2="Optional secondary colour (required for Gradient effect)")
    async def colour(self, ctx: commands.Context, colour1: str, colour2: Optional[str] = None) -> None:
        if not ctx.guild:
            return

        def parse_hex(hex_str: str) -> Optional[int]:
            hex_str = hex_str.lstrip("#")
            try:
                val = int(hex_str, 16)
                if 0 <= val <= 0xFFFFFF:
                    return val
            except ValueError:
                pass
            return None

        c1 = parse_hex(colour1)
        if c1 is None:
            return await ctx.warn("Invalid hex colour. Use format like `#FF0000` or `FF0000`.")

        c2 = None
        if colour2 is not None:
            c2 = parse_hex(colour2)
            if c2 is None:
                return await ctx.warn("Invalid secondary hex colour. Use format like `#00FF00` or `00FF00`.")

        data = await self._get_custom(ctx.guild.id)
        effect_id = data.get("namestyle_effect_id")

        if effect_id == 2 and c2 is None:
            return await ctx.warn("Gradient effect requires two colours. Provide a second colour or change the effect first.")

        await self._set_custom(ctx.guild.id, namestyle_color1=c1, namestyle_color2=c2)
        try:
            await self._apply_namestyle(ctx.guild.id)
        except RuntimeError as e:
            return await ctx.warn(str(e))
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update namestyle colours: `{e}`")

        color_str = f"#{c1:06X}"
        if c2 is not None:
            color_str += f" / #{c2:06X}"
        await ctx.approve(f"Namestyle colours updated to **{color_str}**.", mention_author=False)

    @namestyle.command(name="effect", description="Set the bot's name effect")
    @app_commands.choices(effect=[
        app_commands.Choice(name="Solid", value="1"),
        app_commands.Choice(name="Gradient", value="2"),
        app_commands.Choice(name="Neon", value="3"),
        app_commands.Choice(name="Toon", value="4"),
        app_commands.Choice(name="Pop", value="5"),
        app_commands.Choice(name="Glow", value="6"),
    ])
    @app_commands.describe(effect="The effect to use for the bot's name")
    async def effect(self, ctx: commands.Context, effect: str) -> None:
        if not ctx.guild:
            return

        effect_id = None
        effect_label = None
        if effect.isdigit():
            eid = int(effect)
            if eid in self.EFFECTS:
                effect_id = eid
                effect_label = self.EFFECTS[eid]["label"]
            else:
                return await ctx.warn(f"Invalid effect ID. Choose from: {', '.join(e['label'] for e in self.EFFECTS.values())}")
        else:
            for eid, edata in self.EFFECTS.items():
                if edata["label"].lower() == effect.lower():
                    effect_id = eid
                    effect_label = edata["label"]
                    break
            if effect_id is None:
                return await ctx.warn(f"Invalid effect. Choose from: {', '.join(e['label'] for e in self.EFFECTS.values())}")

        data = await self._get_custom(ctx.guild.id)
        color1 = data.get("namestyle_color1")
        color2 = data.get("namestyle_color2")
        colors_required = self.EFFECTS[effect_id]["colors_required"]

        if colors_required == 2 and (color1 is None or color2 is None):
            return await ctx.warn(f"**{effect_label}** requires two colours. Set a second colour first via `customize namestyle colour`.")

        await self._set_custom(ctx.guild.id, namestyle_effect_id=effect_id)
        try:
            await self._apply_namestyle(ctx.guild.id)
        except RuntimeError as e:
            return await ctx.warn(str(e))
        except (discord.Forbidden, discord.HTTPException) as e:
            return await ctx.warn(f"Failed to update namestyle effect: `{e}`")

        await ctx.approve(f"Namestyle effect updated to **{effect_label}**.", mention_author=False)
