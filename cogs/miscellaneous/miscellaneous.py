from typing import Union
from collections import defaultdict
import requests
import io
import time
import aiohttp
import shazamio
from shazamio import Shazam, Serialize
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
    hybrid_command,
    group,
    Cog,
)
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url
from datetime import datetime, timedelta
from nudenet import NudeDetector
from base.managers.predicates import has_permissions
import asyncio
from psutil import Process
from difflib import get_close_matches

detector = NudeDetector()


class Miscellaneous(CogMeta):
    embed_builder = EmbedBuilder
    embed_script = "{embed}"

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

    @command(name="quickpoll", aliases=["qp"], description="Create a quick poll")
    async def quickpoll(self, ctx: Context):
        await ctx.message.add_reaction("⬆️")
        await ctx.message.add_reaction("⬇️")

    @command(name="screenshot", aliases=["ss"], description="Screenshot a website")
    async def screenshot(self, ctx: Context, *, url: str = None) -> Message:  # type: ignore
        if url is None:
            return await ctx.warn("You need to add a URL.")

        if not match(r"^(http://|https://)", url):
            url = f"https://{url}"
        start_time = time.time()
        async with ctx.typing():
            try:
                async with ctx.bot.browser.borrow_page() as page:
                    await page.emulate_media(color_scheme="dark")
                    await page.goto(url, wait_until="load", timeout=30000)

                    screenshot = await page.screenshot(type="png")

                screenshot_buffer = io.BytesIO(screenshot)
                screenshot_buffer.seek(0)

                exe_time = time.time() - start_time
                execution_time = self.bot.humanize_time(exe_time)
                embed = Embed(color=COLORS.neutral)
                embed.set_image(url="attachment://screenshot.png")
                embed.set_footer(text=f"⏰ took {exe_time: .2f} seconds")
                embed.set_author(
                    name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
                )
                return await ctx.send(
                    embed=embed,
                    file=discord.File(screenshot_buffer, filename="screenshot.png"),
                )
            except Exception as e:
                await ctx.warn(f"Failed to get screenshot: `{e}`")

    @command(name="shazam", description="Get a song from a video")
    async def shazam(self, ctx: Context):
        if ctx.message.reference:
            ref_message = await ctx.channel.fetch_message(
                ctx.message.reference.message_id  # type: ignore
            )
            if ref_message.attachments:
                attachment = ref_message.attachments[0]
            else:
                await ctx.warn(
                    "The replied-to message does not contain a video or audio file."
                )
                return
        elif ctx.message.attachments:
            attachment = ctx.message.attachments[0]
        else:
            await ctx.warn("Please provide a video or audio file.")
            return
        if not (
            attachment.content_type.startswith("audio/")  # type: ignore
            or attachment.content_type.startswith("video/")  # type: ignore
        ):
            await ctx.warn("The provided file is not an audio or video file.")
            return

        async with ctx.typing():
            audio_data = await attachment.read()
            shazam = Shazam()

            try:
                song = await shazam.recognize(audio_data)
                if "track" not in song or "share" not in song["track"]:
                    return await ctx.send("Could not recognize the track.")

                song_cover_url = song["track"]["images"].get("coverart", "")
                return await ctx.embed(
                    description=f"{EMOJIS.SHAZAM} {ctx.author.mention}: Found **[{song['track']['share']['text']}]({song['track']['share']['href']})**",
                    color=0x38A9E1,
                )

            except Exception as E:
                return await ctx.warn(f"An error occurred: **{E}**")

    @command(
        aliases=["ce", "script"],
        description="Create an embed.",
    )
    @has_permissions(manage_messages=True)
    async def createembed(self, ctx: Context, *, script: EmbedScript = None) -> Message:  # type: ignore
        if script is None:
            return await ctx.warn(f"Enter embed script.")
        return await ctx.send(**script)  # type: ignore

    @command(
        name="embedcode",
        aliases=["ec"],
        description="Get embed code from a message url",
    )
    async def embedcode(self, ctx: Context, message_link: str):
        try:
            link_parts = message_link.split("/")
            guild_id = int(link_parts[-3])
            channel_id = int(link_parts[-2])
            message_id = int(link_parts[-1])

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
            embed_dict = embed.to_dict()

            parts = []
            parts.append("{embed}")

            if embed.title:
                parts.append("$v{title:" + embed.title + "}")

            if embed.description:
                parts.append("$v{description:" + embed.description + "}")

            if embed.color:
                parts.append("$v{color:" + hex(embed.color.value)[2:] + "}")

            if embed.author:
                author_parts = [
                    embed.author.name or "",
                    embed.author.icon_url or "",
                    embed.author.url or "",
                ]
                parts.append("$v{author:" + " && ".join(author_parts) + "}")

            for field in embed.fields:
                parts.append(
                    f"$v{{field:{field.name} && {field.value} && {field.inline}}}"
                )

            if embed.footer:
                footer_parts = [embed.footer.text or "", embed.footer.icon_url or ""]
                parts.append("$v{footer:" + " && ".join(footer_parts) + "}")

            if embed.image:
                parts.append("$v{image:" + embed.image.url + "}")  # type: ignore

            if embed.thumbnail:
                parts.append("$v{thumbnail:" + embed.thumbnail.url + "}")  # type: ignore

            if message.components:
                for row in message.components:
                    for button in row.children:
                        label = button.label
                        emoji = button.emoji if button.emoji else "None"
                        url = button.url if hasattr(button, "url") else "None"
                        style = button.style.name if button.style else "None"

                        parts.append(
                            f"$v{{button: label: {label} && emoji: {emoji} && url: {url} && style: {style}}}"
                        )

            embed_script = "".join(parts)
            await ctx.embed(
                description=f"{EMOJIS.APPROVE} {ctx.author.mention}: **Copied embed script: **```\n{embed_script}\n```",
                buttons=[{"label": "Code", "emoji": "🔗"}],
            )

        except Exception as e:
            await ctx.warn(f"An error occurred: {str(e)}")

    async def convert(self, ctx: commands.Context, argument: str):
        x = await EmbedBuilder.to_object(
            EmbedBuilder.embed_replacement(ctx.author, argument)  # type: ignore
        )
        if x[0] or x[1]:
            return {"content": x[0], "embed": x[1], "view": x[2]}
        return {"content": EmbedBuilder.embed_replacement(ctx.author, argument)}  # type: ignore

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

    @command(name="donate", description="Donate to the bot's hosting costs.")
    async def donate(self, ctx: Context):
        return await ctx.embed(
            title="Donate to the bot",
            description=f"<:LTC:1334232446996185118>: **LQdDqiTpTpCz73oQTyMC49zAPodjGNjipp** \n<:PayPal:1334232800361971823>: **heal@psutil.tech**",
            author={"name": ctx.author.name, "icon_url": ctx.author.display_avatar.url},
            thumbnail=self.bot.user.avatar.url,
        )

    @command(
        name="suggest",
        aliases=["suggestion"],
        description="Suggest a feeature for the developers to add.",
    )
    async def suggest(self, ctx: Context, *, suggestion: str):
        embed = Embed(title=f"New suggestion", description=suggestion)
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
        channel = self.bot.get_channel(1335360362601648310)
        await channel.send(embed=embed, content="<@1272545050102071460>")
