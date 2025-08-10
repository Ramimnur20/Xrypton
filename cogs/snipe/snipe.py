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
    has_permissions,
)
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url
from datetime import datetime, timedelta
from nudenet import NudeDetector
import asyncio
from psutil import Process
from difflib import get_close_matches


class Snipe(CogMeta):
    Sniped = {}
    editSnipe = {}
    reactSnipe = {}

    @Cog.listener("on_message_delete")
    async def snipe_listener(self, message: Message) -> None:
        if message.author.bot:
            return

        if message.channel.id not in self.Sniped:
            self.Sniped[message.channel.id] = []

        image_url = None
        if message.attachments:
            image_url = message.attachments[0].url

        self.Sniped[message.channel.id].append(
            {
                "author": str(message.author),
                "author_url": str(message.author.display_avatar.url),
                "content": message.content,
                "image_url": image_url,
                "timestamp": message.created_at,
                "deleted_at": datetime.utcnow(),
            }
        )

    @Cog.listener("on_raw_reaction_remove")
    async def reactionsnip_listener(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        emoji = str(payload.emoji)
        if payload.channel_id not in self.reactSnipe:
            self.reactSnipe[payload.channel_id] = []

        self.reactSnipe[payload.channel_id].append(
            {
                "author": str(payload.user_id),
                "emoji": emoji,
                "message_link": message_link,
                "message_id": payload.message_id,
                "timestamp": datetime.utcnow(),
            }
        )

    @Cog.listener("on_message_edit")
    async def editsnipe_listener(self, before: Message, after: Message) -> None:
        if before.guild and not before.author.bot:
            channel_id = before.channel.id

            if channel_id not in self.editSnipe:
                self.editSnipe[channel_id] = []

            self.editSnipe[channel_id].append(
                {
                    "before_content": before.content,
                    "after_content": after.content,
                    "author": str(before.author),
                    "author_url": str(before.author.display_avatar.url),
                    "timestamp": (before.edited_at),
                    "edited_at": datetime.utcnow(),
                }
            )

    @command(
        name="reactionsnipe",
        description="See recently removed reactions.",
        aliases=["rs"],
    )
    async def reactionsnipe(self, ctx: Context, *, index: int = 1):
        snipes = self.reactSnipe.get(ctx.channel.id, [])
        if not snipes:
            return await ctx.embed(
                description=f"🔎 {ctx.author.mention}: No **reaction removals** found!",
            )

        index -= 1

        if index < 0 or index >= len(snipes):
            return await ctx.warn(f"Invalid index!")

        sniped = snipes[index]
        user_id = sniped.get("author", "N/A")
        emoji = sniped.get("emoji", "")
        timestamp = sniped.get("timestamp", datetime.utcnow())
        original_message_id = sniped.get("message_id")

        embed = Embed(
            description=f"**{await ctx.guild.fetch_member(user_id)}** reacted with *{emoji}* {format_dt(timestamp, 'R')}",
            color=COLORS.neutral,
        )

        channel = self.bot.get_channel(ctx.channel.id)
        original_message = await channel.fetch_message(original_message_id)
        await original_message.reply(embed=embed)

    @command(name="editsnipe", aliases=["es"], description="See edited messages.")
    async def editsnipe(self, ctx: Context, *, index: int = 1):
        editsnipes = self.editSnipe.get(ctx.channel.id, [])
        if not editsnipes:
            return await ctx.embed(
                description=f"🔎 {ctx.author.mention}: No **edited messages** found!"
            )

        index -= 1

        if index < 0 or index >= len(editsnipes):
            return await ctx.warn(f"Invalid index!")

        editsniped = editsnipes[index]
        before = editsniped.get("before_content", "")
        after = editsniped.get("after_content", "")
        author = editsniped.get("author", "N/A")
        author_url = editsniped.get("author_url", "")
        edited = editsniped.get("edited_at", datetime.utcnow())

        time_after_edit = humanize.naturaltime(edited)

        embed = Embed(description=f"**Before:** {before} \n**After:** {after}")
        embed.set_footer(
            text=f"Edited {time_after_edit} ∙ {index + 1}/{len(editsnipes)}"
        )
        embed.set_author(name=author, icon_url=author_url)
        return await ctx.send(embed=embed)

    @command(name="snipe", aliases=["s"], description="See deleted messages.")
    async def snipe(self, ctx: Context, *, index: int = 1):
        sniped_messages = self.Sniped.get(ctx.channel.id, [])
        if not sniped_messages:
            return await ctx.embed(
                description=f"🔎 {ctx.author.mention}: No **deleted messages** found!"
            )

        index -= 1

        if index < 0 or index >= len(sniped_messages):
            return await ctx.warn("Invalid index!")

        sniped_message = sniped_messages[index]
        content = sniped_message.get("content", "")
        author = sniped_message.get("author", "N/A")
        author_icon = sniped_message.get("author_url")
        deleted_at = sniped_message.get("deleted_at", datetime.utcnow())
        image_url = sniped_message.get("image_url")

        time_since_deletion = humanize.naturaltime(deleted_at)

        embed = Embed(description=content)
        embed.set_footer(
            text=f"Deleted {time_since_deletion} ∙ {index + 1}/{len(sniped_messages)}"
        )
        embed.set_author(name=author, icon_url=author_icon)

        if image_url:
            embed.set_image(url=image_url)

        await ctx.send(embed=embed)

    @command(
        name="clearsnipes",
        aliases=["cs"],
        description="Clear all sniped messages in the guild.",
    )
    @has_permissions(manage_messages=True)
    async def clearsnipes(self, ctx: Context):
        cleared = False

        if ctx.message.channel.id in self.Sniped:
            del self.Sniped[ctx.message.channel.id]
            cleared = True

        if ctx.message.channel.id in self.editSnipe:
            del self.editSnipe[ctx.message.channel.id]
            cleared = True

        if ctx.message.channel.id in self.reactSnipe:
            del self.reactSnipe[ctx.message.channel.id]
            cleared = True

        if cleared:
            return await ctx.message.add_reaction("✅")  # type: ignore
        else:
            return await ctx.warn("There are no **sniped** messages in this guild.")
