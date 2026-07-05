from typing import Union
import requests
import io
import time
import aiohttp

from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice
from humanize import naturaltime
import humanize
import os
from datetime import datetime
import time
from jishaku.codeblocks import codeblock_converter

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
    Guild,
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
    has_permissions,
    is_owner,
)
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url
from collections import defaultdict


class Owner(CogMeta):
    @Cog.listener("on_guild_join")
    async def on_guild_join(self, guild: Guild) -> None:
        #       is_whitelisted = await self.bot.pool.fetchval("SELECT 1 FROM guild_whitelist WHERE guild_id = $1", guild.id)  # type: ignore

        #      if is_whitelisted is None:
        #          await guild.leave()

        embed = Embed(description=f"Joined {guild.name} (`{guild.id}`)")
        embed.add_field(
            name="Owner",
            value=f"{guild.owner.name}",  # type: ignore
            inline=True,
        )
        embed.add_field(
            name="Member Count",
            value=f"Total: **{guild.member_count}**",
            inline=True,
        )
        embed.set_footer(
            text=f"{self.bot.user.name} joined a server | We are at {len(self.bot.guilds)} guilds"
        )  # type: ignore
        embed.set_thumbnail(url=guild.icon.url if guild.icon else "https://none.none")

        channel = self.bot.get_channel(
            1333520082151669841
        )  # replace with your channel id - psutil

        if channel:
            return await channel.send(content=f"{guild.id}", embed=embed)  # type: ignore

    @Cog.listener("on_guild_remove")
    async def on_guild_remove(self, guild: Guild) -> None:
        embed = Embed(description=f"Left {guild.name} (`{guild.id}`)")
        embed.add_field(
            name="Owner",
            value=f"{guild.owner.name}",  # type: ignore
            inline=True,
        )
        embed.add_field(
            name="Member Count",
            value=f"Total: **{guild.member_count}**",
            inline=True,
        )
        embed.set_footer(
            text=f"{self.bot.user.name} left a server | We are at {len(self.bot.guilds)} guilds"
        )  # type: ignore
        embed.set_thumbnail(url=guild.icon.url if guild.icon else "https://none.none")
        channel = self.bot.get_channel(
            1333520082151669841
        )  # replace with your channel id - psutil

        if channel:
            return await channel.send(content=f"{guild.id}", embed=embed)  # type: ignore

    @command(name="whitelist", aliases=["wl"])
    @is_owner()
    async def whitelist(self, ctx: Context, *, id: int) -> None:
        if await self.bot.pool.fetch(
            "SELECT guild_id FROM guild_whitelist WHERE guild_id = $1", id
        ):
            await self.bot.pool.execute(
                "DELETE FROM guild_whitelist WHERE guild_id = $1", id
            )
            guild = self.bot.get_guild(id)
            if guild:
                await guild.leave()
            return await ctx.approve(f"Unwhitelisted the guild: `{id}`")  # type: ignore

        await self.bot.pool.execute(
            "INSERT INTO guild_whitelist (guild_id) VALUES ($1)", id
        )
        return await ctx.approve(f"Whitelisted the guild: `{id}`")  # type: ignore

    @command(name="portal")
    @is_owner()
    async def portal(self, ctx: Context, *, id: int) -> None:
        guild = self.bot.get_guild(id)
        await ctx.author.send(await self.generate_invite(guild))
        await ctx.message.delete()

    async def generate_invite(self, guild):
        invite = await guild.text_channels[0].create_invite()
        return invite.url

    @command(name="guilds")
    @is_owner()
    async def guilds(self, ctx: Context):
        entries = [
            f"`{i}`  **{guild.name}** (`{guild.id}`) - {guild.member_count:,} members"
            for i, guild in enumerate(
                sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True),
                start=1,  # type: ignore
            )
        ]

        total_pages = (len(entries) + 9) // 10
        embeds = []
        embed = discord.Embed(
            color=COLORS.neutral,
            title=f"List of Guilds ({len(entries)})",
            description="",
        )

        count = 0

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                    )
                )
                embed = discord.Embed(
                    color=COLORS.neutral,
                    title=f"List of Guilds ({len(entries)})",
                    description="",
                )
                count = 0

        if count > 0:
            embeds.append(
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                )
            )

        if len(embeds) > 1:
            await ctx.paginate(embeds)
        else:
            await ctx.send(embed=embeds[0])

    @command(name="blacklist")
    @is_owner()
    async def blacklist(self, ctx: Context, *, user: Union[User, Member]):
        res = await self.bot.pool.fetch(
            "SELECT user_id FROM blacklist WHERE user_id = $1", user.id
        )
        if res:
            await self.bot.pool.execute(
                "DELETE FROM blacklist WHERE user_id = $1", user.id
            )
            return await ctx.approve(f"**Unblacklisted** {user.name}")

        await self.bot.pool.execute(
            """
            INSERT OR IGNORE INTO blacklist (user_id)
            VALUES (?)
            """,
            user.id,
        )

        return await ctx.approve(f"**Blacklisted** {user.name}")

    @command(name="restart", aliases=["reboot"])
    @is_owner()
    async def restart(self, ctx: Context):
        await ctx.message.add_reaction("✅")
        os.system("pm2 restart Xrypton")

    @command(name="push", description="Push to the github repo")
    @is_owner()
    async def push(self, ctx: Context, *, msg: str):
        os.system(f"git add . && git commit -m '{msg}' && git push")
        await ctx.message.add_reaction("✅")

    @command()
    @is_owner()
    async def pull(self: "Owner", ctx: Context):
        """
        Pull the latest updates from github
        """
        await ctx.invoke(
            self.bot.get_command("jishaku shell"),
            argument=codeblock_converter("git pull"),
        )

    @command(aliases=["py"])
    @is_owner()
    async def eval(self: "Owner", ctx: Context, *, argument: codeblock_converter):
        """
        Run some python code
        """
        return await ctx.invoke(self.bot.get_command("jsk py"), argument=argument)

    @command(name="sql", description="Execute some SQL.")
    @is_owner()
    async def sql(self, ctx: Context, *, argument: str):
        return await ctx.invoke(self.bot.command("jsk sql execute"), argument=argument)
