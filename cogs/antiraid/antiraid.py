from typing import Union
import requests
import io
import re
import time
import aiohttp

from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice
from humanize import naturaltime
import humanfriendly
import time
import datetime

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
import discord
from discord.utils import format_dt, oauth_url
from discord.ext import commands

from psutil import Process
from difflib import get_close_matches

from PIL import Image
from colorthief import ColorThief

from base.managers.predicates import has_permissions


class Antiraid(CogMeta):
    massjoin_cooldown = 10
    massjoin_cache = {}

    @Cog.listener("on_member_join")
    async def check_for_avatar(self, member: Member):
        if member.avatar is None:
            res = await self.bot.pool.fetchrow(
                "SELECT * FROM antiraid WHERE command = $1 AND guild_id = $2",
                "Default Avatar",
                member.guild.id,
            )
            if res is not None:
                res1 = await self.bot.pool.fetchrow(
                    "SELECT * FROM whitelist WHERE guild_id = $1 AND module = $2 AND object_id = $3 AND mode = $4",
                    member.guild.id,
                    "Default Avatar",
                    member.id,
                    "user",
                )
                if res1:
                    return

                if res["punishment"] == "kick":
                    await member.kick(
                        reason="Antiraid: This user does not have a custom avatar."
                    )
                elif res["punishment"] == "ban":
                    await member.ban(
                        reason="Antiraid: This user does not have a custom avatar."
                    )

    @Cog.listener("on_member_join")
    async def new_accounts(self, member: Member):
        print(f"{member} joined {member.guild.name}")

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE command = $1 AND guild_id = $2",
            "New Accounts",
            member.guild.id,
        )
        if not res:
            print("No antiraid settings found for 'newaccounts'.")
            return

        res1 = await self.bot.pool.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1 AND module = $2 AND object_id = $3 AND mode = $4",
            member.guild.id,
            "New Accounts",
            member.id,
            "user",
        )
        if res1:
            print(f"Member {member.id} is whitelisted.")
            return

        account_age_seconds = (
            datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)
        ).total_seconds()
        print(
            f"Account age in seconds: {account_age_seconds}, threshold: {res['seconds']}"
        )

        if account_age_seconds < int(res["seconds"]):
            if res["punishment"] == "kick":
                print(f"Kicking member {member.id}.")
                await member.kick(
                    reason="Antiraid: The account is too young, suspected alt."
                )
            elif res["punishment"] == "ban":
                print(f"Banning member {member.id}.")
                await member.ban(
                    reason="Antiraid: The account is too young, suspected alt."
                )
        else:
            print("Account age is above the threshold.")

    @Cog.listener("on_member_join")
    async def mass_joins(self, member: Member):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE command = $1 AND guild_id = $2",
            "massjoin",
            member.guild.id,
        )
        if res:
            if not self.massjoin_cache.get(str(member.guild.id)):
                self.massjoin_cache[str(member.guild.id)] = []
            self.massjoin_cache[str(member.guild.id)].append(
                tuple([datetime.datetime.now(), member.id])
            )
            expired = [
                mem
                for mem in self.massjoin_cache[str(member.guild.id)]
                if (datetime.datetime.now() - mem[0]).total_seconds()
                > self.massjoin_cooldown
            ]
            for m in expired:
                self.massjoin_cache[str(member.guild.id)].remove(m)
            if len(self.massjoin_cache[str(member.guild.id)]) > res["seconds"]:
                members = [me[1] for me in self.massjoin_cache[str(member.guild.id)]]
                for mem in members:
                    if res["punishment"] == "ban":
                        try:
                            await member.guild.ban(
                                user=self.bot.get_user(mem),
                                reason="AntiRaid: Join raid triggered",
                            )  # type: ignore
                        except:
                            continue
                        else:
                            try:
                                await member.guild.kick(
                                    user=member.guild.get_member(mem),
                                    reason="AntiRaid: Join raid triggered",
                                )  # type: ignore
                            except:
                                continue

    @hybrid_group(
        name="antiraid", invoke_without_command=True, description="Configure antiraid."
    )
    @has_permissions(manage_guild=True)
    async def antiraid(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @antiraid.command(
        name="settings",
        aliases=["stats", "config"],
        description="Check the antiraid configuration.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_settings(self, ctx: Context):
        desc = "**Current Raid State:** "
        enabled = {
            "Mass Join": EMOJIS.DENY,
            "Default Avatar": EMOJIS.DENY,
            "New Accounts": EMOJIS.DENY,
        }
        module_details = {
            "Mass Join": {"punishment": "N/A", "seconds": "N/A"},
            "Default Avatar": {"punishment": "N/A", "seconds": "N/A"},
            "New Accounts": {"punishment": "N/A", "seconds": "N/A"},
        }

        res = await self.bot.pool.fetch(
            "SELECT command, punishment, seconds FROM antiraid WHERE guild_id = $1",
            ctx.guild.id,  # type: ignore
        )

        for result in res:
            command = result["command"]
            punishment = result["punishment"]
            seconds = result["seconds"]

            if command in enabled:
                enabled[command] = EMOJIS.APPROVE
                if command == "New Accounts":
                    seconds = humanfriendly.format_timespan(seconds)
                module_details[command] = {"punishment": punishment, "seconds": seconds}

        if all(status == EMOJIS.APPROVE for status in enabled.values()):
            desc += "Safe"
        else:
            desc += "Unsafe"

        embed = Embed(title="Antiraid Settings", color=COLORS.neutral, description=desc)
        embed.set_author(
            name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
        )

        modules_info = [
            f"**{module}:** {enabled.get(module)} (Do: **{details['punishment']}**, Threshold: **{details['seconds']}**)"
            for module, details in module_details.items()
        ]

        embed.add_field(name="Modules", value="\n".join(modules_info))

        embed.set_thumbnail(
            url=ctx.guild.icon.url if ctx.guild.icon else "https://none.none"  # type: ignore
        )
        await ctx.reply(embed=embed)

    @antiraid.group(
        name="whitelist",
        aliases=["wl"],
        invoke_without_command=True,
        description="Whitelist a user for the antiraid",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_whitelist(self, ctx: Context, *, member: Member):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1 AND object_id = $2 AND module = $3 AND mode = $4",
            ctx.guild.id,  # type: ignore
            member.id,
            "antiraid",
            "user",
        )
        if res:
            return await ctx.warn(
                f"{member.mention} is already whitelisted for **antiraid**."
            )

        await self.bot.pool.execute(
            "INSERT INTO whitelist VALUES ($1,$2,$3,$4)",
            ctx.guild.id,  # type: ignore
            "antiraid",
            member.id,
            "user",
        )
        return await ctx.approve(
            f"{member.mention} will now be **ignored** on antiraid events."
        )

    @antiraid.command(
        name="unwhitelist",
        aliases=["unwl"],
        description="Unwhitelist a user on the antiraid",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_unwhitelist(self, ctx: Context, *, member: Member):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1 AND object_id = $2 AND module = $3 AND mode = $4",
            ctx.guild.id,  # type: ignore
            member.id,
            "antiraid",
            "user",
        )
        if not res:
            return await ctx.warn(
                f"**{member.mention}** is not whitelisted for **anti raid**"
            )
        await self.bot.pool.execute(
            "DELETE FROM whitelist WHERE guild_id = $1 AND object_id = $2 AND module = $3",
            ctx.guild.id,  # type: ignore
            member.id,
            "antiraid",
        )
        return await ctx.approve(
            f"**{member.mention}** is **no longer** ignored on antiraid events."
        )

    @antiraid.group(
        name="massjoin",
        invoke_without_command=True,
        description="Configure antiraid massjoin.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_massjoin(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @antiraid_massjoin.command(
        name="enable", aliases=["on"], description="Enable massjoin event."
    )
    @has_permissions(manage_guild=True)
    async def antiraid_massjoin_enable(self, ctx: Context, *, args: str):
        split_args = args.split()

        if "--do" not in split_args or "--threshold" not in split_args:
            return await ctx.warn(
                "Invalid syntax! Use: `,antiraid massjoin on --do <punishment> --threshold <joins>`"
            )

        try:
            do_index = split_args.index("--do") + 1
            threshold_index = split_args.index("--threshold") + 1

            punishment = split_args[do_index]
            threshold = split_args[threshold_index]

            if punishment not in ["kick", "ban"]:
                return await ctx.warn("Punishment must be either **kick** or **ban**")

            joins = int(threshold)
            if joins <= 0:
                raise ValueError("Threshold must be a positive number of joins.")
        except (IndexError, ValueError):
            return await ctx.warn(
                "Invalid syntax! `--threshold` must be a positive integer representing the join threshold."
            )

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,  # type: ignore
            "Mass Join",
        )

        if res:
            await self.bot.pool.execute(
                "UPDATE antiraid SET punishment = $1, seconds = $2 WHERE guild_id = $3 AND command = $4",
                punishment,
                joins,
                ctx.guild.id,  # type: ignore
                "Mass Join",
            )
            return await ctx.approve(
                f"Updated **Massjoin** antiraid. Punishment is set to **{punishment}**, threshold is set to **{joins} joins**."
            )

        await self.bot.pool.execute(
            "INSERT INTO antiraid (guild_id, command, punishment, seconds) VALUES ($1, $2, $3, $4)",
            ctx.guild.id,  # type: ignore
            "Mass Join",
            punishment,
            joins,
        )
        return await ctx.approve(
            f"Added **Massjoin** antiraid. Punishment is set to **{punishment}**, threshold is set to **{joins} joins**."
        )

    @antiraid_massjoin.command(
        name="disable", aliases=["off"], description="Disable massjoin event"
    )
    @has_permissions(manage_guild=True)
    async def antiraid_massjoin_disable(self, ctx: Context):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,  # type: ignore
            "Mass Join",
        )
        if not res:
            return await ctx.warn(f"Mass Join protection **isn't** enabled.")

        await self.bot.pool.execute(
            "DELETE FROM antiraid WHERE command = $1 AND guild_id = $2",
            "Mass Join",
            ctx.guild.id,  # type: ignore
        )
        return await ctx.approve("Mass Join protection has been **disabled**")

    @antiraid.group(
        name="newaccounts",
        invoke_without_command=True,
        description="Configure antiraid new accounts.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_newaccounts(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @antiraid_newaccounts.command(
        name="on", aliases=["enable"], description="Enable antiraid new accounts."
    )
    async def newaccounts_on(self, ctx: Context, *, args: str):
        split_args = args.split()

        if "--do" not in split_args or "--threshold" not in split_args:
            return await ctx.warn(
                "Invalid syntax! Use: `,antiraid newaccounts on --do <punishment> --threshold <days>`"
            )

        try:
            do_index = split_args.index("--do") + 1
            threshold_index = split_args.index("--threshold") + 1

            punishment = split_args[do_index]
            threshold = split_args[threshold_index]

            if punishment not in ["kick", "ban"]:
                return await ctx.warn("Punishment must be either **kick** or **ban**")

            days = int(threshold)
            if days <= 0:
                raise ValueError("Threshold must be a positive number of days.")

            time_seconds = days * 86400
        except (IndexError, ValueError):
            return await ctx.warn("Invalid syntax! `--threshold` must be in days.")

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE command = $1 AND guild_id = $2",
            "New Accounts",
            ctx.guild.id,  # type: ignore
        )

        if res:
            await self.bot.pool.execute(
                "UPDATE antiraid SET punishment = $1, seconds = $2 WHERE guild_id = $3 AND command = $4",
                punishment,
                time_seconds,
                ctx.guild.id,  # type: ignore
                "New Accounts",
            )
            return await ctx.approve(
                f"Updated **New Accounts** antiraid. Punishment is set to **{punishment}**, account age threshold is set to **{days} days**."
            )

        await self.bot.pool.execute(
            "INSERT INTO antiraid (guild_id, command, punishment, seconds) VALUES ($1, $2, $3, $4)",
            ctx.guild.id,  # type: ignore
            "New Accounts",
            punishment,
            time_seconds,
        )
        return await ctx.approve(
            f"Added **New Accounts** antiraid. Punishment is set to **{punishment}**, account age threshold is set to **{days} days**."
        )

    @antiraid_newaccounts.command(
        name="disable", aliases=["off"], description="Disable antiraid new accounts"
    )
    @has_permissions(manage_guild=True)
    async def antiraid_newaccounts_disable(self, ctx: Context):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,  # type: ignore
            "New Accounts",
        )
        if not res:
            return await ctx.warn(f"New Account protection **isn't** enabled.")

        await self.bot.pool.execute(
            "DELETE FROM antiraid WHERE command = $1 AND guild_id = $2",
            "New Accounts",
            ctx.guild.id,  # type: ignore
        )
        return await ctx.approve("New Account protection has been **disabled**")

    @antiraid_newaccounts.command(
        name="whitelist",
        aliases=["wl"],
        description="Allow a user to join the server if under aged.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_newaccounts_whitelist(self, ctx: Context, *, user: User):
        check = await ctx.bot.pool.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1 AND module = $2 AND object_id = $3 AND mode = $4",
            ctx.guild.id,  # type: ignore
            "New Accounts",
            user.id,
            "user",
        )

        if check:
            await self.bot.pool.execute(
                "DELETE FROM whitelist WHERE guild_id = $1 AND module = $2 AND object_id = $3 AND mode = $4",
                ctx.guild.id,  # type: ignore
                "New Accounts",
                user.id,
                "user",
            )
            return await ctx.approve(
                f"**{user.display_name}** has been removed from the whitelist."
            )

        await ctx.bot.pool.execute(
            "INSERT INTO whitelist (guild_id, module, object_id, mode) VALUES ($1, $2, $3, $4)",
            ctx.guild.id,  # type: ignore
            "New Accounts",
            user.id,
            "user",
        )
        return await ctx.approve(
            f"**{user.display_name}** is now whitelisted for **antiraid newaccounts** and can join."
        )

    @antiraid.group(
        name="defaultavatar",
        aliases=["dav", "defaultpfp"],
        invoke_without_command=True,
        description="Configure antiraid default avatar.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_defaultavatar(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @antiraid_defaultavatar.command(
        name="enable", aliases=["on"], description="Enable antiraid default avatar"
    )
    @has_permissions(manage_guild=True)
    async def antiraid_defaultavatar_enable(self, ctx: Context, *, args: str):
        split_args = args.split()

        if "--do" not in split_args:
            return await ctx.warn(
                "Invalid syntax! Use: `,antiraid defaultavatar on --do <punishment>`"
            )

        try:
            do_index = split_args.index("--do") + 1
            punishment = split_args[do_index]
        except IndexError:
            return await ctx.warn("You must specify a punishment after `--do`.")

        if punishment not in ["kick", "ban"]:
            return await ctx.warn("Punishment must be either **kick** or **ban**.")

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,  # type: ignore
            "Default Avatar",
        )

        if res:
            await self.bot.pool.execute(
                "UPDATE antiraid SET punishment = $1 WHERE guild_id = $2 AND command = $3",
                punishment,
                ctx.guild.id,  # type: ignore
                "Default Avatar",
            )
            return await ctx.approve(
                f"Updated **Default Avatar** antiraid. Punishment is now set to **{punishment}**."
            )

        await self.bot.pool.execute(
            "INSERT INTO antiraid (guild_id, command, punishment, seconds) VALUES ($1, $2, $3, $4)",
            ctx.guild.id,  # type: ignore
            "Default Avatar",
            punishment,
            0,
        )
        return await ctx.approve(
            f"Added **Default Avatar** antiraid. Punishment is set to **{punishment}**."
        )

    @antiraid_defaultavatar.command(
        name="disable", aliases=["off"], description="Disable antiraid default avatar."
    )
    @has_permissions(manage_guild=True)
    async def antiraid_defaultavatar_disable(self, ctx: Context):
        res = await self.bot.pool.fetchrow(
            "SELECT * FROM antiraid WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,  # type: ignore
            "Default Avatar",
        )
        if not res:
            return await ctx.warn(f"Default Avatar protection **isn't** enabled.")

        await self.bot.pool.execute(
            "DELETE FROM antiraid WHERE command = $1 AND guild_id = $2",
            "Default Avatar",
            ctx.guild.id,  # type: ignore
        )
        return await ctx.approve("Default Avatar protection has been **disabled**")

    @antiraid_whitelist.command(
        name="view", description="View the whitelisted users on the antiraid module."
    )
    async def antiraid_whitelist_view(self, ctx: Context):
        rows = await self.bot.pool.fetch(
            "SELECT object_id FROM whitelist WHERE guild_id = $1 AND mode = $2",
            ctx.guild.id,  # type: ignore
            "user",
        )

        if not rows:
            return await ctx.warn("No **whitelisted** users found.")

        entries = []
        for i, row in enumerate(rows, start=1):
            user_id = row["object_id"]
            user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)  # type: ignore
            username = user.name if user else "Unknown User"
            entries.append(f"`{i}` **{username}** (`{user_id}`)")

        total_pages = (len(entries) + 9) // 10
        embeds = []
        embed = discord.Embed(
            color=COLORS.neutral,
            title=f"Antiraid Whitelists",
            description="",
        )
        embed.set_author(
            name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
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
                    title=f"Whitelisted Users for {ctx.guild.name} ({len(entries)})",  # type: ignore
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
