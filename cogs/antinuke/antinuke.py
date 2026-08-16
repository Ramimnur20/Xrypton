import discord
from base.managers.predicates import example
from collections import defaultdict
from asyncio import Lock
from random import sample
from datetime import datetime
from typing import Dict, List

from discord import Embed, Message, RawReactionActionEvent, utils
from discord.ext import commands, tasks
from discord.ext.commands import Cog, group, has_permissions

from base.context import Context
from base.managers.types import CogMeta

from base.managers.predicates import example, has_permissions
from typing import TYPE_CHECKING
from datetime import timedelta

import discord
from discord import Embed, Member, Message, TextChannel
from discord.utils import utcnow
from discord.ext.commands import Cog, command, group

from base.managers.types import CogMeta
from base.context import Context
from base.config import COLORS

from base.managers.predicates import example, has_permissions
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

class AntiNukeModule:
    def __init__(self, module: str, punishment: str, threshold: int, toggled: bool):
        self.module = module
        self.punishment = punishment
        self.threshold = threshold
        self.toggled = toggled

    @classmethod
    async def from_database(cls, pool, guild_id: int, module: str):
        result = await pool.fetchrow(
            "SELECT * FROM antinuke_modules WHERE guild_id = $1 AND module = $2",
            guild_id,
            module,
        )
        if not result:
            return None
        return cls(
            result["module"],
            result["punishment"],
            result["threshold"],
            result["toggled"],
        )

    async def update(self, pool, guild_id: int):
        await pool.execute(
            "UPDATE antinuke_modules SET punishment = $1, threshold = $2, toggled = $3 WHERE guild_id = $4 AND module = $5",
            self.punishment,
            self.threshold,
            self.toggled,
            guild_id,
            self.module,
        )


class AntiNukeUser:
    def __init__(self, module: str, user_id: int, last_action: datetime, amount: int):
        self.module = module
        self.user_id = user_id
        self.last_action = last_action
        self.amount = amount


class AntiNukeEvents(CogMeta):
    def __init__(self, bot):
        self.bot = bot
        self.actions: Dict[int, List[AntiNukeUser]] = {}
        self.locks = defaultdict(Lock)

    async def cog_load(self):
        self.giveaway_check.start()

    async def cog_unload(self):
        self.giveaway_check.stop()

    @tasks.loop(seconds=10)
    async def giveaway_check(self):
        async with self.locks["giveaway"]:
            try:
                giveaways = await self.bot.pool.fetch(
                    "SELECT * FROM giveaway WHERE ended = false AND ends_at <= $1",
                    utils.utcnow(),
                )
                for giveaway in giveaways:
                    channel = self.bot.get_channel(giveaway["channel_id"])
                    if channel:
                        self.bot.dispatch("giveaway_end", channel.guild, channel, giveaway)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return

        enabled = await self.bot.pool.fetchrow(
            "SELECT * FROM ancfg WHERE guild_id = $1", member.guild.id
        )
        if not enabled:
            return

        module = await AntiNukeModule.from_database(
            self.bot.pool, member.guild.id, "Bot"
        )
        if not module or not module.toggled:
            return

        admin = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
            member.guild.id,
            member.id,
        )

        whitelisted = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
            member.guild.id,
            member.id,
        )

        if admin or whitelisted:
            return

        await member.ban(
            reason=f"{self.bot.user.name} Anti-Nuke: Protection (Anti-Bot)"
        )

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        if entry.user is None or entry.user.id == entry.guild.me.id:
            return

        enabled = await self.bot.pool.fetchrow(
            "SELECT * FROM ancfg WHERE guild_id = $1", entry.guild.id
        )
        if not enabled:
            return

        if entry.action in [discord.AuditLogAction.ban, discord.AuditLogAction.unban]:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Ban"
            )
            if module and module.toggled:
                await self.take_action(
                    entry.guild.id, entry.user.id, entry.guild.owner.id, module
                )

        elif entry.action == discord.AuditLogAction.kick:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Kick"
            )
            if module and module.toggled:
                await self.take_action(
                    entry.guild.id, entry.user.id, entry.guild.owner.id, module
                )

        elif entry.action in [
            discord.AuditLogAction.channel_delete,
            discord.AuditLogAction.channel_update,
            discord.AuditLogAction.channel_create,
        ]:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Channels"
            )
            if module and module.toggled:
                await self.take_action(
                    entry.guild.id, entry.user.id, entry.guild.owner.id, module
                )

        elif entry.action in [
            discord.AuditLogAction.role_delete,
            discord.AuditLogAction.role_create,
        ]:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Roles"
            )
            if module and module.toggled:
                await self.take_action(
                    entry.guild.id, entry.user.id, entry.guild.owner.id, module
                )

        elif entry.action == discord.AuditLogAction.member_role_update:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Permissions"
            )
            if not module or not module.toggled:
                return

            admin = await self.bot.pool.fetchrow(
                "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
                entry.guild.id,
                entry.user.id,
            )
            whitelisted = await self.bot.pool.fetchrow(
                "SELECT * FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
                entry.guild.id,
                entry.user.id,
            )

            if admin or whitelisted or entry.user.id == entry.guild.owner.id:
                return

            for role in entry.after.roles:
                if role not in entry.before.roles and role.permissions.administrator:
                    await self.take_action(
                        entry.guild.id, entry.user.id, entry.guild.owner.id, module
                    )
                    await entry.target.remove_roles(role)
                    return

        elif entry.action in [
            discord.AuditLogAction.webhook_create,
            discord.AuditLogAction.webhook_delete,
        ]:
            module = await AntiNukeModule.from_database(
                self.bot.pool, entry.guild.id, "Webhook"
            )
            if module and module.toggled:
                await self.take_action(
                    entry.guild.id, entry.user.id, entry.guild.owner.id, module
                )

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.vanity_url_code != after.vanity_url_code:
            enabled = await self.bot.pool.fetchrow(
                "SELECT * FROM ancfg WHERE guild_id = $1", after.id
            )
            if not enabled:
                return

            user = None
            async for entry in before.audit_logs(
                limit=1, action=discord.AuditLogAction.guild_update
            ):
                user = entry.user

            if user:
                module = await AntiNukeModule.from_database(
                    self.bot.pool, after.id, "Vanity"
                )
                if module and module.toggled:
                    await self.take_action(after.id, user.id, after.owner.id, module)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        if message.mention_everyone:
            enabled = await self.bot.pool.fetchrow(
                "SELECT * FROM ancfg WHERE guild_id = $1", message.guild.id
            )
            if not enabled:
                return

            module = await AntiNukeModule.from_database(
                self.bot.pool, message.guild.id, "Massmention"
            )
            if module and module.toggled:
                admin = await self.bot.pool.fetchrow(
                    "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
                    message.guild.id,
                    message.author.id,
                )
                whitelisted = await self.bot.pool.fetchrow(
                    "SELECT * FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
                    message.guild.id,
                    message.author.id,
                )

                if (
                    not admin
                    and not whitelisted
                    and message.author.id != message.guild.owner.id
                ):
                    await self.take_action(
                        message.guild.id,
                        message.author.id,
                        message.guild.owner.id,
                        module,
                    )
                    try:
                        await message.delete()
                    except Exception:
                        pass

    async def take_action(
        self,
        guild_id: int,
        user_id: int,
        owner_id: int,
        module: AntiNukeModule,
    ):
        admin = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        whitelisted = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

        if (
            whitelisted
            or admin
            or user_id == self.bot.user.id
            or user_id == owner_id
        ):
            return

        if guild_id not in self.actions:
            self.actions[guild_id] = [
                AntiNukeUser(module.module, user_id, datetime.now(), 1)
            ]
            return

        found = False
        for action in self.actions[guild_id]:
            if action.user_id == user_id and action.module == module.module:
                found = True
                if (datetime.now() - action.last_action).total_seconds() > 60:
                    self.remove_action(guild_id, user_id, module.module)
                    self.actions[guild_id].append(
                        AntiNukeUser(module.module, user_id, datetime.now(), 1)
                    )
                    return

                if action.amount >= module.threshold:
                    self.remove_action(guild_id, user_id, module.module)
                    await self.send_action(guild_id, user_id, module)
                    return

                action.amount += 1
                self.remove_action(guild_id, user_id, module.module)
                self.actions[guild_id].append(
                    AntiNukeUser(
                        module.module,
                        user_id,
                        datetime.now(),
                        action.amount,
                    )
                )
                return

        if not found:
            self.actions[guild_id].append(
                AntiNukeUser(module.module, user_id, datetime.now(), 1)
            )

    async def send_action(
        self,
        guild_id: int,
        user_id: int,
        module: AntiNukeModule,
    ):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        user = await self.bot.fetch_user(user_id)
        if not user:
            return

        reason = f"{self.bot.user.name} Anti-Nuke: Protection {module.module} (Anti-{module.module})"

        if module.punishment.lower() == "ban":
            await guild.ban(user=user, reason=reason)
        elif module.punishment.lower() == "kick":
            await guild.kick(user=user, reason=reason)
        elif module.punishment.lower() == "warn":
            try:
                await user.send(
                    f"{self.bot.user.name} Anti-Nuke: Protection {module.module} (Anti-{module.module})\n"
                    "**You have been warned**, further actions will result in a punishment decided by relevant staff."
                )
            except Exception:
                pass
        elif module.punishment.lower() == "strip":
            member = guild.get_member(user_id)
            if member:
                dangerous_roles = [
                    role
                    for role in member.roles
                    if any(
                        [
                            role.permissions.administrator,
                            role.permissions.manage_channels,
                            role.permissions.manage_roles,
                            role.permissions.manage_webhooks,
                            role.permissions.mention_everyone,
                            role.permissions.manage_expressions,
                            role.permissions.moderate_members,
                            role.permissions.manage_messages,
                            role.permissions.manage_guild,
                            role.permissions.ban_members,
                            role.permissions.kick_members,
                            role.permissions.mute_members,
                        ]
                    )
                ]
                if dangerous_roles:
                    await member.remove_roles(*dangerous_roles, reason=reason)

        log_embed = Embed(
            title=f"Anti-Nuke: {module.module}",
            description=f"Action taken by {self.bot.user.name}",
            color=0xD3D6F1,
            timestamp=datetime.now(),
        )
        log_embed.add_field(name="User", value=f"<@{user_id}>", inline=True)
        log_embed.add_field(name="Action", value=module.punishment, inline=True)
        log_embed.set_footer(
            text=f"{self.bot.user.name} Anti-Nuke",
            icon_url=self.bot.user.avatar.url,
        )

        log_channel_id = await self.bot.pool.fetchval(
            "SELECT channel_id FROM logging WHERE guild_id = $1", guild_id
        )

        if log_channel_id:
            channel = self.bot.get_channel(log_channel_id)
            if channel:
                try:
                    await channel.send(embed=log_embed)
                except Exception:
                    pass

    def remove_action(self, guild_id: int, user_id: int, module: str):
        if guild_id not in self.actions:
            return

        for pos, action in enumerate(self.actions[guild_id]):
            if action.user_id == user_id and action.module == module:
                del self.actions[guild_id][pos]
                return


async def has_admin(ctx: Context) -> bool:
    from base.config import CLIENT

    if (
        ctx.author.id in CLIENT.OWNER
        or ctx.author.id == ctx.guild.owner.id
    ):
        return True

    admin = await ctx.bot.pool.fetchrow(
        "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
        ctx.guild.id,
        ctx.author.id,
    )
    if not admin:
        await ctx.warn("You do not have **anti-nuke admin**")
        return False
    return True


async def is_enabled(ctx: Context) -> bool:
    module = await ctx.bot.pool.fetchrow(
        "SELECT * FROM ancfg WHERE guild_id = $1", ctx.guild.id
    )
    if not module:
        await ctx.warn(
            "AntiNuke is not **enabled** in this server. Use `antinuke enable` to **enable** it."
        )
        return False
    return True


class AntiNuke(CogMeta):
    def __init__(self, bot):
        self.bot = bot
        self.modules = [
            "Ban",
            "Kick",
            "Bot",
            "Roles",
            "Vanity",
            "Webhook",
            "Channels",
            "Permissions",
            "Massmention",
        ]
    @example(",antinuke")
    @commands.hybrid_group(invoke_without_command=True, aliases=["an"])
    @has_permissions(administrator=True)
    async def antinuke(self, ctx: Context):
        if not await has_admin(ctx):
            return
        await ctx.send_help(ctx.command)
    @example(",ticket settings")
    @antinuke.command(aliases=["config"])
    @has_permissions(administrator=True)
    async def settings(self, ctx: Context):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        embed = Embed(
            title=f"Anti-Nuke Settings - {ctx.guild.name}",
            color=ctx.config.colors.information,
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        for name in self.modules:
            module = await AntiNukeModule.from_database(self.bot.pool, ctx.guild.id, name)
            status = (
                ctx.config.emojis.context.approve
                if module and module.toggled
                else ctx.config.emojis.context.deny
            )
            embed.add_field(
                name=f"{name}: {status}",
                value=(
                    f"Action: `{module.punishment if module else 'None'}`\n"
                    f"Threshold: `{module.threshold if module else 'None'}`"
                ),
                inline=True,
            )

        await ctx.send(embed=embed)
    @example(",antinuke whitelist @voby")
    @antinuke.command(aliases=["wl"])
    @has_permissions(administrator=True)
    async def whitelist(self, ctx: Context, user: discord.User):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        whitelist = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            user.id,
        )

        if whitelist:
            await self.bot.pool.execute(
                "DELETE FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                user.id,
            )
            await ctx.approve(
                f"**{user.name}** has been **unwhitelisted** in this server."
            )
        else:
            await self.bot.pool.execute(
                "INSERT INTO antinuke_whitelist VALUES ($1, $2)",
                ctx.guild.id,
                user.id,
            )
            await ctx.approve(
                f"**{user.name}** has been **whitelisted** in this server."
            )
    @example(",antinuke admin @voby")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def admin(self, ctx: Context, user: discord.User):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        admin = await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            user.id,
        )

        if admin:
            await self.bot.pool.execute(
                "DELETE FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                user.id,
            )
            await ctx.approve(
                f"**{user.name}** has been **removed** from the **Anti-Nuke Admin** list in this server."
            )
        else:
            await self.bot.pool.execute(
                "INSERT INTO antinuke_admins VALUES ($1, $2)",
                ctx.guild.id,
                user.id,
            )
            await ctx.approve(
                f"**{user.name}** has been **added** to the **Anti-Nuke Admin** list in this server."
            )
    @example(",antinuke whitelisted")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def whitelisted(self, ctx: Context):
        if not await has_admin(ctx):
            return

        whitelisted = await self.bot.pool.fetch(
            "SELECT * FROM antinuke_whitelist WHERE guild_id = $1", ctx.guild.id
        )

        if not whitelisted:
            return await ctx.warn("No users are **whitelisted** in this server.")

        embed = Embed(
            title=f"Anti-Nuke Whitelisted Members - {ctx.guild.name}",
            color=ctx.config.colors.information,
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.description = "\n".join(
            [
                f"{ctx.guild.get_member(user['user_id']).name if ctx.guild.get_member(user['user_id']) else 'Unknown'} ({user['user_id']})"
                for user in whitelisted
            ]
        )

        await ctx.send(embed=embed)
    @example(",antinuke admins")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def admins(self, ctx: Context):
        if not await has_admin(ctx):
            return

        admins = await self.bot.pool.fetch(
            "SELECT * FROM antinuke_admins WHERE guild_id = $1", ctx.guild.id
        )

        if not admins:
            return await ctx.warn("No users are **Anti-Nuke Admins** in this server.")

        embed = Embed(
            title=f"Anti-Nuke Admins - {ctx.guild.name}",
            color=ctx.config.colors.information,
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.description = "\n".join(
            [
                f"{ctx.guild.get_member(user['user_id']).name if ctx.guild.get_member(user['user_id']) else 'Unknown'} ({user['user_id']})"
                for user in admins
            ]
        )

        await ctx.send(embed=embed)
    @example(",antiraid massjoin on --do ban --threshold 5")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def enable(self, ctx: Context):
        if not await has_admin(ctx):
            return

        enabled = await self.bot.pool.fetchrow(
            "SELECT * FROM ancfg WHERE guild_id = $1", ctx.guild.id
        )

        if enabled:
            return await ctx.warn("AntiNuke is already **enabled** in this server.")

        await self.bot.pool.execute("INSERT INTO ancfg VALUES ($1)", ctx.guild.id)

        modules = await self.bot.pool.fetch(
            "SELECT * FROM antinuke_modules WHERE guild_id = $1", ctx.guild.id
        )

        if not modules:
            for name in self.modules:
                await self.bot.pool.execute(
                    "INSERT INTO antinuke_modules VALUES ($1, $2, $3, $4, $5)",
                    ctx.guild.id,
                    name,
                    "ban",
                    1,
                    False,
                )

        await ctx.approve("Anti-Nuke has been **enabled** in this server.")
    @example(",antiraid massjoin off")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def disable(self, ctx: Context):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        await self.bot.pool.execute(
            "DELETE FROM ancfg WHERE guild_id = $1", ctx.guild.id
        )
        await ctx.approve("Anti-Nuke has been **disabled** in this server.")
    @example(",level toggle")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def toggle(self, ctx: Context, module: str):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        module_name = module.capitalize()
        if module_name not in self.modules:
            return await ctx.warn(
                f"The module `{module}` is not a valid **Anti-Nuke module**."
            )

        an_module = await AntiNukeModule.from_database(
            self.bot.pool, ctx.guild.id, module_name
        )
        if not an_module:
            return await ctx.warn("Module not found.")

        an_module.toggled = not an_module.toggled
        await an_module.update(self.bot.pool, ctx.guild.id)

        await ctx.approve(
            f"Anti-Nuke module `{module}` has been **{'Enabled' if an_module.toggled else 'Disabled'}**."
        )
    @example(",antinuke threshold ban 3")
    @antinuke.command()
    @has_permissions(administrator=True)
    async def threshold(self, ctx: Context, module: str, threshold: int):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        module_name = module.capitalize()
        if module_name not in self.modules:
            return await ctx.warn(
                f"The module `{module}` is not a valid **Anti-Nuke module**."
            )

        an_module = await AntiNukeModule.from_database(
            self.bot.pool, ctx.guild.id, module_name
        )
        if not an_module:
            return await ctx.warn("Module not found.")

        an_module.threshold = threshold
        await an_module.update(self.bot.pool, ctx.guild.id)

        await ctx.approve(
            f"Anti-Nuke module `{module}` threshold has been set to `{threshold}`."
        )
    @example(",antinuke action ban ban")
    @antinuke.command(aliases=["punishment"])
    @has_permissions(administrator=True)
    async def action(self, ctx: Context, module: str, action: str):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        module_name = module.capitalize()
        if module_name not in self.modules:
            return await ctx.warn(
                f"The module `{module}` is not a valid **Anti-Nuke module**."
            )

        if action.lower() not in ["ban", "warn", "kick", "strip"]:
            return await ctx.warn(
                "The action `{action}` is not a valid action. Use `ban`, `warn`, `kick` or `strip`."
            )

        an_module = await AntiNukeModule.from_database(
            self.bot.pool, ctx.guild.id, module_name
        )
        if not an_module:
            return await ctx.warn("Module not found.")

        an_module.punishment = action.lower()
        await an_module.update(self.bot.pool, ctx.guild.id)

        await ctx.approve(
            f"Anti-Nuke module `{module}` action has been set to `{action}`."
        )


if TYPE_CHECKING:
    from base.Xrypton import Bot


TIMEOUT_DURATION = timedelta(days=1)


class HoneypotView(discord.ui.LayoutView):
    def __init__(self, *, trigger_count: int, punishment: str):
        super().__init__()
        punishment_word = {
            "softban": "softban",
            "ban": "ban",
            "kick": "kick",
            "timeout": "timeout",
        }.get(punishment, "softban")

        self.container1 = discord.ui.Container(
        discord.ui.Section(
            discord.ui.TextDisplay(content="## DO NOT SEND MESSAGES IN THIS CHANNEL\n\nThis channel is used to catch spam bots. Any messages sent here will result in **a softban**.\n**Kicks**: 0"),
            accessory=discord.ui.Thumbnail(
                media="https://images-ext-1.discordapp.net/external/B6MYTzrgbMIlsjwgjHvxuRagMPvnyYcoyyN9GNEeA9o/https/honeypot.riskymh.dev/honeypot.png?format=webp&quality=lossless&width=320&height=320",
            ),
        ),
    )


class Honeypot(CogMeta):
    @example(",honeypot")
    @group(
        name="honeypot",
        invoke_without_command=True,
        description="Anti-scam/anti-compromised-account protection.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @example(",honeypot channel")
    @honeypot.group(
        name="channel",
        invoke_without_command=True,
        description="Manage the honeypot channel.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_channel(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",honeypot channel set #channel")
    @honeypot_channel.command(
        name="set",
        description="Set the honeypot channel for the guild.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_channel_set(self, ctx: Context, channel: TextChannel):
        existing = await self.bot.pool.fetchrow(
            "SELECT channel_id, trigger_count, punishment FROM honeypot WHERE guild_id = $1",
            ctx.guild.id,
        )

        is_first_setup = existing is None
        current_punishment = existing["punishment"] if existing else "softban"

        await self.bot.pool.execute(
            """
            INSERT INTO honeypot (guild_id, channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )

        if is_first_setup:
            view = HoneypotView(trigger_count=0, punishment=current_punishment)
            try:
                await channel.send(view=view)
            except Exception:
                pass

        return await ctx.approve(f"Honeypot channel set to {channel.mention}.")
    @example(",honeypot channel remove")
    @honeypot_channel.command(
        name="remove",
        description="Remove/disable the honeypot channel.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_channel_remove(self, ctx: Context):
        existing = await self.bot.pool.fetchrow(
            "SELECT channel_id FROM honeypot WHERE guild_id = $1",
            ctx.guild.id,
        )

        if not existing or existing["channel_id"] is None:
            return await ctx.warn("There is no honeypot channel configured to remove.")

        await self.bot.pool.execute(
            "UPDATE honeypot SET channel_id = NULL WHERE guild_id = $1",
            ctx.guild.id,
        )

        return await ctx.approve("Honeypot channel has been removed.")

    @example(",honeypot alert")
    @honeypot.group(
        name="alert",
        invoke_without_command=True,
        description="Manage the honeypot alert channel.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_alert(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",honeypot alert set #channel")
    @honeypot_alert.command(
        name="set",
        description="Set the channel that receives honeypot alerts.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_alert_set(self, ctx: Context, channel: TextChannel):
        await self.bot.pool.execute(
            """
            INSERT INTO honeypot (guild_id, alert_channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET alert_channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )

        return await ctx.approve(f"Alert channel set to {channel.mention}.")
    @example(",honeypot alert remove")
    @honeypot_alert.command(
        name="remove",
        description="Remove the honeypot alert channel.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_alert_remove(self, ctx: Context):
        existing = await self.bot.pool.fetchrow(
            "SELECT alert_channel_id FROM honeypot WHERE guild_id = $1",
            ctx.guild.id,
        )

        if not existing or existing["alert_channel_id"] is None:
            return await ctx.warn("There is no alert channel configured to remove.")

        await self.bot.pool.execute(
            "UPDATE honeypot SET alert_channel_id = NULL WHERE guild_id = $1",
            ctx.guild.id,
        )

        return await ctx.approve("Alert channel has been removed.")
    @example(",honeypot punishment ban")
    @honeypot.command(
        name="punishment",
        description="Set the punishment for honeypot triggers.",
    )
    @has_permissions(manage_guild=True)
    async def honeypot_punishment(self, ctx: Context, punishment: str):
        punishment = punishment.lower()
        valid_punishments = ["ban", "kick", "timeout"]

        if punishment not in valid_punishments:
            return await ctx.warn(
                f"Invalid punishment. Must be one of: {', '.join(valid_punishments)}."
            )

        await self.bot.pool.execute(
            """
            INSERT INTO honeypot (guild_id, punishment)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET punishment = $2
            """,
            ctx.guild.id,
            punishment,
        )

        return await ctx.approve(f"Honeypot punishment set to **{punishment}**.")

    @Cog.listener()
    async def on_message(self, message: Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        channel_id = message.channel.id

        row = await self.bot.pool.fetchrow(
            "SELECT channel_id, punishment, alert_channel_id FROM honeypot WHERE guild_id = $1",
            guild_id,
        )

        if not row or row["channel_id"] is None or channel_id != row["channel_id"]:
            return

        punishment = row["punishment"]

        try:
            await message.delete()
        except Exception:
            pass

        member = message.author
        guild = message.guild
        action_taken = "unknown"

        try:
            if punishment == "softban":
                await member.ban(
                    reason="Honeypot: Triggered honeypot channel",
                    delete_message_days=7,
                )
                await guild.unban(member, reason="Honeypot: Softban completed")
                action_taken = "softban"
            elif punishment == "ban":
                await member.ban(reason="Honeypot: Triggered honeypot channel")
                action_taken = "ban"
            elif punishment == "kick":
                await member.kick(reason="Honeypot: Triggered honeypot channel")
                action_taken = "kick"
            elif punishment == "timeout":
                await member.timeout(
                    utcnow() + TIMEOUT_DURATION,
                    reason="Honeypot: Triggered honeypot channel",
                )
                action_taken = "timeout"
        except Exception:
            pass

        await self.bot.pool.execute(
            "UPDATE honeypot SET trigger_count = trigger_count + 1 WHERE guild_id = $1",
            guild_id,
        )

        if row["alert_channel_id"]:
            try:
                alert_channel = self.bot.get_channel(row["alert_channel_id"])
                if alert_channel:
                    embed = Embed(
                        title="Honeypot Triggered",
                        description=(
                            f"User {member.mention} (`{member.id}`) triggered the honeypot.\n"
                            f"Action taken: **{action_taken}**"
                        ),
                        color=COLORS.neutral,
                        timestamp=utcnow(),
                    )
                    await alert_channel.send(embed=embed)
            except Exception:
                pass


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
    @example(",antiraid")
    @hybrid_group(
        name="antiraid", invoke_without_command=True, description="Configure antiraid."
    )
    @has_permissions(manage_guild=True)
    async def antiraid(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",ticket settings")
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

    @example(",antinuke whitelist @voby")
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
    @example(",antinuke unwhitelist @voby")
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

    @example(",antiraid massjoin")
    @antiraid.group(
        name="massjoin",
        invoke_without_command=True,
        description="Configure antiraid massjoin.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_massjoin(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",antiraid massjoin on --do ban --threshold 5")
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
    @example(",antiraid massjoin off")
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

    @example(",antiraid newaccounts")
    @antiraid.group(
        name="newaccounts",
        invoke_without_command=True,
        description="Configure antiraid new accounts.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_newaccounts(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",antiraid newaccounts on --do ban --threshold 7")
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
    @example(",antiraid massjoin off")
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
    @example(",antinuke whitelist @voby")
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

    @example(",antiraid defaultavatar")
    @antiraid.group(
        name="defaultavatar",
        aliases=["dav", "defaultpfp"],
        invoke_without_command=True,
        description="Configure antiraid default avatar.",
    )
    @has_permissions(manage_guild=True)
    async def antiraid_defaultavatar(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    @example(",antiraid massjoin on --do ban --threshold 5")
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
    @example(",antiraid massjoin off")
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
    @example(",eco shop view")
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
