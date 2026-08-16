import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks
from loguru import logger

from base.context import Context
from base.managers.types import CogMeta


MODULES = (
    "botadd",
    "botremove",
    "roleadd",
    "roleremove",
    "rolechange",
    "channelcreate",
    "channeldelete",
    "serversettings",
)
PUNISHMENTS = ("none", "strip_roles", "kick", "ban", "quarantine")


def is_guild_owner():
    async def predicate(ctx: Context) -> bool:
        if not ctx.guild or ctx.author.id != ctx.guild.owner_id:
            await ctx.warn("Only the **server owner** can manage antinuke admins.")
            return False
        return True

    return commands.check(predicate)


def is_antinuke_admin():
    async def predicate(ctx: Context) -> bool:
        if not ctx.guild:
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        allowed = await ctx.bot.pool.fetchval(
            "SELECT 1 FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not allowed:
            await ctx.warn("Only an **antinuke admin** or the server owner can do that.")
            return False
        return True

    return commands.check(predicate)


class DisableConfirmation(discord.ui.View):
    def __init__(self, cog: "AntiNuke", ctx: Context):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("You cannot confirm this action.", ephemeral=True)
        return False

    @discord.ui.button(label="Disable", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.disable_guild(self.ctx.guild)
        await interaction.response.edit_message(
            embed=self.cog.embed("AntiNuke disabled", "Protection is disabled. Configuration is retained for 14 days."),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.cog.embed("AntiNuke unchanged", "Disable request cancelled."), view=None
        )
        self.stop()


class SettingsView(discord.ui.View):
    def __init__(self, cog: "AntiNuke", guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.selected_module: Optional[str] = None
        module_options = [discord.SelectOption(label=module, value=module) for module in MODULES]
        punishment_options = [discord.SelectOption(label=value, value=value) for value in PUNISHMENTS]
        self.module_select = discord.ui.Select(
            placeholder="Toggle a module", options=module_options, custom_id="antinuke:toggle"
        )
        self.punishment_select = discord.ui.Select(
            placeholder="Set punishment", options=punishment_options, custom_id="antinuke:punishment"
        )
        self.module_select.callback = self.toggle_module
        self.punishment_select.callback = self.set_punishment
        self.add_item(self.module_select)
        self.add_item(self.punishment_select)

    async def _authorized(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        if not guild:
            return False
        if interaction.user.id == guild.owner_id:
            return True
        allowed = await self.cog.bot.pool.fetchval(
            "SELECT 1 FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2",
            guild.id,
            interaction.user.id,
        )
        if not allowed:
            await interaction.response.send_message("You are not authorized to change AntiNuke settings.", ephemeral=True)
            return False
        return True

    async def toggle_module(self, interaction: discord.Interaction):
        if not await self._authorized(interaction):
            return
        module = self.module_select.values[0]
        self.selected_module = module
        row = await self.cog.get_module(interaction.guild.id, module)
        enabled = not bool(row["enabled"])
        await self.cog.bot.pool.execute(
            "UPDATE antinuke_modules SET enabled = $1 WHERE guild_id = $2 AND module = $3",
            int(enabled), interaction.guild.id, module,
        )
        await interaction.response.edit_message(
            embed=await self.cog.settings_embed(interaction.guild), view=self
        )

    async def set_punishment(self, interaction: discord.Interaction):
        if not await self._authorized(interaction):
            return
        module = self.selected_module
        if not module:
            return await interaction.response.send_message("Select a module first, then choose its punishment.", ephemeral=True)
        punishment = self.punishment_select.values[0]
        await self.cog.bot.pool.execute(
            "UPDATE antinuke_modules SET punishment = $1 WHERE guild_id = $2 AND module = $3",
            punishment, interaction.guild.id, module,
        )
        await interaction.response.edit_message(
            embed=await self.cog.settings_embed(interaction.guild), view=self
        )


class AntiNuke(CogMeta):
    """Protect guilds from unauthorized destructive audit-log actions."""

    def __init__(self, bot):
        super().__init__(bot)
        self.audit_cache: dict[int, tuple[datetime, list[discord.AuditLogEntry]]] = {}
        self.audit_locks = defaultdict(asyncio.Lock)
        self.retention_cleanup.start()

    def cog_unload(self):
        self.retention_cleanup.cancel()

    async def cog_load(self):
        await self.ensure_schema()

    async def ensure_schema(self):
        statements = (
            "CREATE TABLE IF NOT EXISTS antinuke (guild_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, disabled_at TIMESTAMP, log_channel_id INTEGER)",
            "CREATE TABLE IF NOT EXISTS antinuke_modules (guild_id INTEGER, module TEXT, enabled INTEGER DEFAULT 1, punishment TEXT DEFAULT 'ban', PRIMARY KEY (guild_id, module))",
            "CREATE TABLE IF NOT EXISTS antinuke_admins (guild_id INTEGER, user_id INTEGER, added_by INTEGER, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id, user_id))",
            "CREATE TABLE IF NOT EXISTS antinuke_whitelist (guild_id INTEGER, user_id INTEGER, added_by INTEGER, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id, user_id))",
            "CREATE TABLE IF NOT EXISTS antinuke_incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, module TEXT, offender_id INTEGER, target_id INTEGER, punishment_applied TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reason TEXT)",
            "CREATE TABLE IF NOT EXISTS antinuke_quarantine (guild_id INTEGER PRIMARY KEY, role_id INTEGER)",
        )
        for statement in statements:
            await self.bot.pool.execute(statement)
        for table in ("antinuke_admins", "antinuke_whitelist"):
            for column in ("added_by INTEGER", "added_at TIMESTAMP"):
                try:
                    await self.bot.pool.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
                except Exception:
                    pass
        # The live database may predate newer columns; add any that are missing.
        # `except` swallows the harmless "duplicate column" error when present.
        for table, column in (
            ("antinuke_modules", "enabled INTEGER DEFAULT 1"),
            ("antinuke_modules", "punishment TEXT DEFAULT 'ban'"),
            ("antinuke", "enabled INTEGER DEFAULT 0"),
            ("antinuke", "disabled_at TIMESTAMP"),
            ("antinuke", "log_channel_id INTEGER"),
        ):
            try:
                await self.bot.pool.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except Exception:
                pass

    def embed(self, title: str, description: str, color: Optional[discord.Color] = None) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color or discord.Color.blurple())
        embed.set_footer(text="Xrypton AntiNuke")
        return embed

    async def ensure_guild(self, guild_id: int):
        await self.bot.pool.execute(
            "INSERT OR IGNORE INTO antinuke (guild_id, enabled) VALUES ($1, 0)", guild_id
        )
        for module in MODULES:
            await self.bot.pool.execute(
                "INSERT OR IGNORE INTO antinuke_modules (guild_id, module, enabled, punishment) VALUES ($1, $2, 1, 'ban')",
                guild_id, module,
            )

    async def get_config(self, guild_id: int):
        await self.ensure_guild(guild_id)
        return await self.bot.pool.fetchrow("SELECT * FROM antinuke WHERE guild_id = $1", guild_id)

    async def get_module(self, guild_id: int, module: str):
        await self.ensure_guild(guild_id)
        return await self.bot.pool.fetchrow(
            "SELECT * FROM antinuke_modules WHERE guild_id = $1 AND module = $2", guild_id, module
        )

    async def is_exempt(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id in (guild.owner_id, getattr(self.bot.user, "id", None)):
            return True
        for table in ("antinuke_admins", "antinuke_whitelist"):
            if await self.bot.pool.fetchval(
                f"SELECT 1 FROM {table} WHERE guild_id = $1 AND user_id = $2", guild.id, user_id
            ):
                return True
        return False

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        config = await self.get_config(guild.id)
        rows = await self.bot.pool.fetch(
            "SELECT module, enabled, punishment FROM antinuke_modules WHERE guild_id = $1 ORDER BY module", guild.id
        )
        lines = [f"`{row['module']}`: **{'enabled' if row['enabled'] else 'disabled'}** | `{row['punishment']}`" for row in rows]
        return self.embed(
            "AntiNuke settings",
            f"Protection: **{'enabled' if config['enabled'] else 'disabled'}**\n\n" + "\n".join(lines),
        )

    async def disable_guild(self, guild: discord.Guild):
        await self.ensure_guild(guild.id)
        await self.bot.pool.execute(
            "UPDATE antinuke SET enabled = 0, disabled_at = $1 WHERE guild_id = $2", datetime.now(timezone.utc), guild.id
        )
        await self.bot.pool.execute("UPDATE antinuke_modules SET enabled = 0 WHERE guild_id = $1", guild.id)

    @commands.hybrid_group(name="antinuke", aliases=["an"], invoke_without_command=True, description="Configure anti-nuke protection")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def antinuke(self, ctx: Context):
        if not ctx.guild:
            return await ctx.warn("This command can only be used in a server.")
        await self.ensure_guild(ctx.guild.id)
        return await ctx.send(embed=self.embed(
            "AntiNuke",
            "`admin`, `whitelist`, `enable`, `disable`, `settings`, `log`, or configure a module:\n"
            "`botadd`, `botremove`, `roleadd`, `roleremove`, `rolechange`, `channelcreate`, `channeldelete`, `serversettings`\n\n"
            "Use `,antinuke <module> [true/false] [none/strip_roles/kick/ban/quarantine]`.",
        ))

    @antinuke.group(name="admin", invoke_without_command=True)
    async def admin(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @admin.command(name="add")
    @is_guild_owner()
    async def admin_add(self, ctx: Context, user: discord.Member):
        if user.id == ctx.guild.owner_id:
            return await ctx.warn("The server owner is already always authorized.")
        await self.ensure_guild(ctx.guild.id)
        await self.bot.pool.execute(
            "INSERT OR IGNORE INTO antinuke_admins (guild_id, user_id, added_by, added_at) VALUES ($1, $2, $3, $4)",
            ctx.guild.id, user.id, ctx.author.id, datetime.now(timezone.utc),
        )
        return await ctx.approve(f"Added {user.mention} as an **antinuke admin**.")

    @admin.command(name="remove")
    @is_guild_owner()
    async def admin_remove(self, ctx: Context, user: discord.Member):
        await self.bot.pool.execute(
            "DELETE FROM antinuke_admins WHERE guild_id = $1 AND user_id = $2", ctx.guild.id, user.id
        )
        return await ctx.approve(f"Removed {user.mention} from **antinuke admins**.")

    @admin.command(name="list")
    async def admin_list(self, ctx: Context):
        rows = await self.bot.pool.fetch("SELECT user_id FROM antinuke_admins WHERE guild_id = $1", ctx.guild.id)
        if not rows:
            return await ctx.warn("There are no antinuke admins configured.")
        return await self.send_list(ctx, "AntiNuke admins", [f"<@{row['user_id']}> (`{row['user_id']}`)" for row in rows])

    @antinuke.group(name="whitelist", invoke_without_command=True)
    async def whitelist(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @whitelist.command(name="add")
    @is_antinuke_admin()
    async def whitelist_add(self, ctx: Context, user: discord.Member):
        if user.id in (ctx.guild.owner_id, self.bot.user.id):
            return await ctx.warn("That user is already exempt from AntiNuke enforcement.")
        await self.ensure_guild(ctx.guild.id)
        await self.bot.pool.execute(
            "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id, added_by, added_at) VALUES ($1, $2, $3, $4)",
            ctx.guild.id, user.id, ctx.author.id, datetime.now(timezone.utc),
        )
        return await ctx.approve(f"Whitelisted {user.mention} from AntiNuke enforcement.")

    @whitelist.command(name="remove")
    @is_antinuke_admin()
    async def whitelist_remove(self, ctx: Context, user: discord.Member):
        await self.bot.pool.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = $1 AND user_id = $2", ctx.guild.id, user.id
        )
        return await ctx.approve(f"Removed {user.mention} from the AntiNuke whitelist.")

    @whitelist.command(name="list")
    async def whitelist_list(self, ctx: Context):
        rows = await self.bot.pool.fetch("SELECT user_id FROM antinuke_whitelist WHERE guild_id = $1", ctx.guild.id)
        if not rows:
            return await ctx.warn("There are no whitelisted users.")
        return await self.send_list(ctx, "AntiNuke whitelist", [f"<@{row['user_id']}> (`{row['user_id']}`)" for row in rows])

    async def send_list(self, ctx: Context, title: str, entries: list[str]):
        embeds = []
        for offset in range(0, len(entries), 10):
            embed = self.embed(title, "\n".join(f"`{i + 1}` {entry}" for i, entry in enumerate(entries[offset:offset + 10], offset)))
            embed.set_footer(text=f"Xrypton AntiNuke | Page {len(embeds) + 1}/{(len(entries) + 9) // 10}")
            embeds.append(embed)
        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await ctx.paginate(embeds)

    @antinuke.command(name="enable")
    @is_antinuke_admin()
    async def enable(self, ctx: Context):
        await self.ensure_guild(ctx.guild.id)
        await self.bot.pool.execute("UPDATE antinuke SET enabled = 1, disabled_at = NULL WHERE guild_id = $1", ctx.guild.id)
        await self.bot.pool.execute("UPDATE antinuke_modules SET enabled = 1 WHERE guild_id = $1", ctx.guild.id)
        return await ctx.approve("Enabled **AntiNuke** and all modules.")

    @antinuke.command(name="disable")
    @is_antinuke_admin()
    async def disable(self, ctx: Context):
        return await ctx.send(
            embed=self.embed("Disable AntiNuke?", "This disables all protection modules. Settings are retained for 14 days."),
            view=DisableConfirmation(self, ctx),
        )

    @antinuke.command(name="settings")
    async def settings(self, ctx: Context):
        await self.ensure_guild(ctx.guild.id)
        return await ctx.send(embed=await self.settings_embed(ctx.guild), view=SettingsView(self, ctx.guild.id))

    @antinuke.group(name="log", invoke_without_command=True)
    async def log(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @log.command(name="add")
    @is_antinuke_admin()
    async def log_add(self, ctx: Context, channel: discord.TextChannel):
        await self.ensure_guild(ctx.guild.id)
        await self.bot.pool.execute("UPDATE antinuke SET log_channel_id = $1 WHERE guild_id = $2", channel.id, ctx.guild.id)
        return await ctx.approve(f"AntiNuke logging now uses {channel.mention}; any previous log channel was replaced.")

    @log.command(name="remove")
    @is_antinuke_admin()
    async def log_remove(self, ctx: Context):
        await self.bot.pool.execute("UPDATE antinuke SET log_channel_id = NULL WHERE guild_id = $1", ctx.guild.id)
        return await ctx.approve("Removed the AntiNuke log channel.")

    @log.command(name="status")
    async def log_status(self, ctx: Context):
        config = await self.get_config(ctx.guild.id)
        channel_id = config["log_channel_id"]
        value = f"<#{channel_id}>" if channel_id else "Not set"
        return await ctx.send(embed=self.embed("AntiNuke log channel", value))

    async def configure_module(self, ctx: Context, module: str, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        if module not in MODULES:
            return await ctx.warn(f"Invalid module. Choose from: {', '.join(MODULES)}.")
        if punishment and punishment.lower() not in PUNISHMENTS:
            return await ctx.warn(f"Invalid punishment. Choose from: {', '.join(PUNISHMENTS)}.")
        row = await self.get_module(ctx.guild.id, module)
        if enabled is None and punishment is None:
            return await ctx.send(embed=self.embed("AntiNuke module", f"`{module}`: **{'enabled' if row['enabled'] else 'disabled'}** | `{row['punishment']}`"))
        await self.bot.pool.execute(
            "UPDATE antinuke_modules SET enabled = $1, punishment = $2 WHERE guild_id = $3 AND module = $4",
            int(enabled) if enabled is not None else row["enabled"], punishment.lower() if punishment else row["punishment"], ctx.guild.id, module,
        )
        final_enabled = bool(row["enabled"]) if enabled is None else enabled
        final_punishment = punishment.lower() if punishment else row["punishment"]
        return await ctx.approve(
            f"Updated `{module}`: **{'enabled' if final_enabled else 'disabled'}** | `{final_punishment}`."
        )

    @antinuke.command(name="botadd")
    @is_antinuke_admin()
    async def botadd(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "botadd", enabled, punishment)

    @antinuke.command(name="botremove")
    @is_antinuke_admin()
    async def botremove(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "botremove", enabled, punishment)

    @antinuke.command(name="roleadd")
    @is_antinuke_admin()
    async def roleadd(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "roleadd", enabled, punishment)

    @antinuke.command(name="roleremove")
    @is_antinuke_admin()
    async def roleremove(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "roleremove", enabled, punishment)

    @antinuke.command(name="rolechange")
    @is_antinuke_admin()
    async def rolechange(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "rolechange", enabled, punishment)

    @antinuke.command(name="channelcreate")
    @is_antinuke_admin()
    async def channelcreate(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "channelcreate", enabled, punishment)

    @antinuke.command(name="channeldelete")
    @is_antinuke_admin()
    async def channeldelete(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "channeldelete", enabled, punishment)

    @antinuke.command(name="serversettings")
    @is_antinuke_admin()
    async def serversettings(self, ctx: Context, enabled: Optional[bool] = None, punishment: Optional[str] = None):
        return await self.configure_module(ctx, "serversettings", enabled, punishment)

    async def get_audit_entry(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: Optional[int] = None):
        now = datetime.now(timezone.utc)
        cached = self.audit_cache.get(guild.id)
        if cached and now - cached[0] < timedelta(seconds=2):
            entries = cached[1]
        else:
            async with self.audit_locks[guild.id]:
                cached = self.audit_cache.get(guild.id)
                if cached and now - cached[0] < timedelta(seconds=2):
                    entries = cached[1]
                else:
                    entries = []
                    async for entry in guild.audit_logs(limit=20):
                        entries.append(entry)
                    self.audit_cache[guild.id] = (now, entries)
        for entry in entries:
            entry_target_id = getattr(entry.target, "id", None)
            if entry.action == action and (target_id is None or entry_target_id == target_id):
                if (now - entry.created_at).total_seconds() < 15:
                    return entry
        return None

    async def resolve_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: Optional[int] = None):
        for delay in (0, 0.75, 1.25):
            if delay:
                await asyncio.sleep(delay)
                self.audit_cache.pop(guild.id, None)
            entry = await self.get_audit_entry(guild, action, target_id)
            if entry and entry.user:
                return entry.user
        return None

    async def handle_violation(self, guild: discord.Guild, module: str, offender: discord.abc.User, reason: str, target=None):
        config = await self.get_config(guild.id)
        module_config = await self.get_module(guild.id, module)
        if not config["enabled"] or not module_config["enabled"] or await self.is_exempt(guild, offender.id):
            return
        member = guild.get_member(offender.id)
        applied = module_config["punishment"]
        if not member:
            applied = "no permission to enforce (offender is no longer in the guild)"
        elif member.id == guild.owner_id or member.id == self.bot.user.id:
            return
        elif guild.me and member.top_role >= guild.me.top_role:
            applied = "no permission to enforce (role hierarchy)"
        else:
            try:
                if applied == "strip_roles":
                    roles = [role for role in member.roles if role != guild.default_role and role < guild.me.top_role]
                    if roles:
                        await member.remove_roles(*roles, reason=f"AntiNuke: {reason}")
                elif applied == "kick":
                    await member.kick(reason=f"AntiNuke: {reason}")
                elif applied == "ban":
                    await member.ban(reason=f"AntiNuke: {reason}", delete_message_seconds=0)
                elif applied == "quarantine":
                    role = await self.get_quarantine_role(guild)
                    roles = [role for role in member.roles if role != guild.default_role and role != role and role < guild.me.top_role]
                    if roles:
                        await member.remove_roles(*roles, reason=f"AntiNuke quarantine: {reason}")
                    await member.add_roles(role, reason=f"AntiNuke quarantine: {reason}")
                elif applied == "none":
                    applied = "none (log only)"
            except discord.Forbidden:
                applied = "no permission to enforce"
            except discord.HTTPException as error:
                logger.warning("AntiNuke enforcement failed in guild {}: {}", guild.id, error)
                applied = "enforcement failed"
        target_id = getattr(target, "id", None)
        await self.bot.pool.execute(
            "INSERT INTO antinuke_incidents (guild_id, module, offender_id, target_id, punishment_applied, timestamp, reason) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            guild.id, module, offender.id, target_id, applied, datetime.now(timezone.utc), reason,
        )
        await self.log_incident(guild, module, offender, target, applied, reason)

    async def get_quarantine_role(self, guild: discord.Guild) -> discord.Role:
        role_id = await self.bot.pool.fetchval("SELECT role_id FROM antinuke_quarantine WHERE guild_id = $1", guild.id)
        role = guild.get_role(role_id) if role_id else None
        if role:
            return role
        role = await guild.create_role(name="AntiNuke Quarantine", permissions=discord.Permissions.none(), reason="AntiNuke quarantine setup")
        await self.bot.pool.execute("INSERT OR REPLACE INTO antinuke_quarantine (guild_id, role_id) VALUES ($1, $2)", guild.id, role.id)
        return role

    async def log_incident(self, guild, module, offender, target, applied, reason):
        config = await self.get_config(guild.id)
        channel = guild.get_channel(config["log_channel_id"]) if config["log_channel_id"] else None
        if not isinstance(channel, discord.abc.Messageable):
            return
        target_value = getattr(target, "mention", None) or (f"`{getattr(target, 'id', target)}`" if target else "Not applicable")
        embed = self.embed(
            "AntiNuke incident",
            f"**Module:** `{module}`\n**Offender:** {offender.mention} (`{offender.id}`)\n"
            f"**Target:** {target_value}\n**Punishment:** `{applied}`\n**Reason:** {reason}\n"
            f"**Timestamp:** <t:{int(datetime.now(timezone.utc).timestamp())}:F>",
            discord.Color.red(),
        )
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def process_event(self, guild, module, action, target, reason):
        try:
            config = await self.get_config(guild.id)
            module_config = await self.get_module(guild.id, module)
            if not config["enabled"] or not module_config["enabled"]:
                return
            actor = await self.resolve_actor(guild, action, getattr(target, "id", None))
            if actor:
                await self.handle_violation(guild, module, actor, reason, target)
        except Exception as error:
            logger.exception("AntiNuke listener failed for {} in guild {}: {}", module, guild.id, error)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            await self.process_event(member.guild, "botadd", discord.AuditLogAction.bot_add, member, "Unauthorized bot added")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            await self.process_event(member.guild, "botremove", discord.AuditLogAction.kick, member, "Bot removed from the guild")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            before_roles = {role.id for role in before.roles}
            after_roles = {role.id for role in after.roles}
            if after_roles - before_roles:
                await self.process_event(after.guild, "roleadd", discord.AuditLogAction.member_role_update, after, "Role granted to member")
            elif before_roles - after_roles:
                await self.process_event(after.guild, "roleremove", discord.AuditLogAction.member_role_update, after, "Role removed from member")
        except Exception as error:
            logger.exception("AntiNuke member role listener failed: {}", error)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self.process_event(role.guild, "rolechange", discord.AuditLogAction.role_create, role, "Role created")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.process_event(role.guild, "rolechange", discord.AuditLogAction.role_delete, role, "Role deleted")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await self.process_event(after.guild, "rolechange", discord.AuditLogAction.role_update, after, "Role edited")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self.process_event(channel.guild, "channelcreate", discord.AuditLogAction.channel_create, channel, "Channel created")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self.process_event(channel.guild, "channeldelete", discord.AuditLogAction.channel_delete, channel, "Channel deleted")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        await self.process_event(after, "serversettings", discord.AuditLogAction.guild_update, after, "Server settings changed")

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        await self.process_event(guild, "botadd", discord.AuditLogAction.bot_add, None, "Guild integrations changed")

    @tasks.loop(hours=6)
    async def retention_cleanup(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        rows = await self.bot.pool.fetch("SELECT guild_id FROM antinuke WHERE disabled_at IS NOT NULL AND disabled_at < $1", cutoff)
        for row in rows:
            guild_id = row["guild_id"]
            for table in ("antinuke_modules", "antinuke_admins", "antinuke_whitelist", "antinuke_incidents", "antinuke_quarantine", "antinuke"):
                await self.bot.pool.execute(f"DELETE FROM {table} WHERE guild_id = $1", guild_id)

    @retention_cleanup.before_loop
    async def before_retention_cleanup(self):
        await self.bot.wait_until_ready()
