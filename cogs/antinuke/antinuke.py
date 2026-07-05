import discord
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
    if (
        ctx.author.id in ctx.bot.owner_ids
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

    @commands.hybrid_group(invoke_without_command=True, aliases=["an"])
    @has_permissions(administrator=True)
    async def antinuke(self, ctx: Context):
        if not await has_admin(ctx):
            return
        await ctx.send_help(ctx.command)

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

    @antinuke.command()
    @has_permissions(administrator=True)
    async def disable(self, ctx: Context):
        if not await has_admin(ctx) or not await is_enabled(ctx):
            return

        await self.bot.pool.execute(
            "DELETE FROM ancfg WHERE guild_id = $1", ctx.guild.id
        )
        await ctx.approve("Anti-Nuke has been **disabled** in this server.")

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