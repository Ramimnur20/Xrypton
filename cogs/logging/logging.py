from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Union, Dict, Any, List, Set, Tuple, Sequence

import discord
from discord import (
    Embed,
    Member,
    User,
    Role,
    TextChannel,
    VoiceChannel,
    StageChannel,
    CategoryChannel,
    Thread,
    Guild,
    Emoji,
    GuildSticker,
    ButtonStyle,
    PermissionOverwrite,
)
from discord.ext import commands
from discord.ext.commands import hybrid_group, group, command, Cog
from loguru import logger

from base.config import COLORS, EMOJIS
from base.context import Context
from base.managers.predicates import has_permissions, example
from base.managers.types import CogMeta
from base.managers.paginator import Paginator
from base.managers.snipe_cache import (
    Sniped,
    editSnipe,
    reactSnipe,
    rawMessageCache,
    record_raw_message,
    record_delete,
    record_edit,
)
from base.managers.mod_logger import log_moderation_action

LOG_CHANNEL_NAMES = {
    "server": "server-logs",
    "member": "member-logs",
    "vc": "vc-logs",
    "moderation": "moderation-logs",
    "message": "message-logs",
}


class SetupConfirmationView(discord.ui.View):
    """View shown when ,log aio is run on an already configured guild."""

    def __init__(self, cog: Logging, ctx: Context, category_name: str = "Logs"):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.category_name = category_name
        self.value: Optional[str] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("You cannot confirm this action.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Relink & Verify", style=ButtonStyle.blurple, emoji="🔄")
    async def relink(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = "relink"
        self.stop()

    @discord.ui.button(label="Recreate Fresh", style=ButtonStyle.danger, emoji="🗑️")
    async def recreate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.value = "recreate"
        self.stop()

    @discord.ui.button(label="Cancel", style=ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = "cancel"
        self.stop()
        await interaction.response.edit_message(
            embed=Embed(
                description=f"{EMOJIS.APPROVE} Setup cancelled. Existing log channels were preserved.",
                color=COLORS.neutral,
            ),
            view=None,
        )

class Logging(CogMeta):
    """General-purpose activity and moderation logging system for Xrypton."""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self._config_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        self._ignore_cache: Dict[int, Set[Tuple[str, int]]] = {}
        self._audit_cache: Dict[int, List[discord.AuditLogEntry]] = {}
        self._send_queues: Dict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._queue_tasks: Dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Ensure logging tables exist in the database."""
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS logging_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                category_id INTEGER,
                server_channel_id INTEGER,
                member_channel_id INTEGER,
                vc_channel_id INTEGER,
                moderation_channel_id INTEGER,
                message_channel_id INTEGER
            );
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS logging_ignores (
                guild_id INTEGER,
                target_type TEXT,
                target_id INTEGER,
                PRIMARY KEY (guild_id, target_type, target_id)
            );
            """
        )

    async def _get_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Fetch and cache guild logging configuration."""
        if guild_id in self._config_cache:
            return self._config_cache[guild_id]

        row = await self.bot.pool.fetchrow(
            """
            SELECT enabled, category_id, server_channel_id, member_channel_id,
                   vc_channel_id, moderation_channel_id, message_channel_id
            FROM logging_config WHERE guild_id = $1
            """,
            guild_id,
        )
        if row:
            config = {
                "enabled": bool(row["enabled"]),
                "category_id": row["category_id"],
                "server_channel_id": row["server_channel_id"],
                "member_channel_id": row["member_channel_id"],
                "vc_channel_id": row["vc_channel_id"],
                "moderation_channel_id": row["moderation_channel_id"],
                "message_channel_id": row["message_channel_id"],
            }
        else:
            config = None

        self._config_cache[guild_id] = config
        return config

    async def _get_ignores(self, guild_id: int) -> Set[Tuple[str, int]]:
        """Fetch and cache guild logging ignore entries."""
        if guild_id in self._ignore_cache:
            return self._ignore_cache[guild_id]

        rows = await self.bot.pool.fetch(
            "SELECT target_type, target_id FROM logging_ignores WHERE guild_id = $1",
            guild_id,
        )
        ignores = {(r["target_type"], int(r["target_id"])) for r in rows}
        self._ignore_cache[guild_id] = ignores
        return ignores

    def _invalidate_cache(self, guild_id: int) -> None:
        """Invalidate cached config and ignore rules for a guild."""
        self._config_cache.pop(guild_id, None)
        self._ignore_cache.pop(guild_id, None)

    async def get_audit_entry(
        self,
        guild: Guild,
        action: discord.AuditLogAction,
        target_id: Optional[int] = None,
        max_age_seconds: float = 20.0,
    ) -> Optional[discord.AuditLogEntry]:
        """Fetch the most recent matching audit log entry with retry/backoff."""
        if not guild.me.guild_permissions.view_audit_log:
            return None

        now = datetime.now(timezone.utc)
        for delay in (0, 0.75, 1.25):
            if delay:
                await asyncio.sleep(delay)
            try:
                async for entry in guild.audit_logs(limit=8, action=action):
                    entry_target_id = getattr(entry.target, "id", None)
                    if target_id is None or entry_target_id == target_id:
                        entry_time = entry.created_at
                        if entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                        age = (now - entry_time).total_seconds()
                        if abs(age) <= max_age_seconds:
                            return entry
            except (discord.Forbidden, discord.HTTPException):
                return None
        return None

    def _is_ignored(
        self,
        ignores: Set[Tuple[str, int]],
        actors: Optional[Sequence[Union[Member, User, int]]] = None,
        targets: Optional[Sequence[Union[Member, User, int]]] = None,
        channels: Optional[Sequence[Union[discord.abc.GuildChannel, Thread, int]]] = None,
        roles: Optional[Sequence[Union[Role, int]]] = None,
    ) -> bool:
        """Check if any participant, channel, or role is in the guild ignore set."""
        if not ignores:
            return False

        # Check users/actors
        for user_obj in (actors or []) + (targets or []):
            uid = user_obj.id if hasattr(user_obj, "id") else user_obj
            if ("user", uid) in ignores:
                return True
            if isinstance(user_obj, Member):
                for role in user_obj.roles:
                    if ("role", role.id) in ignores:
                        return True

        # Check channels
        for chan_obj in (channels or []):
            cid = chan_obj.id if hasattr(chan_obj, "id") else chan_obj
            if ("channel", cid) in ignores:
                return True
            if isinstance(chan_obj, Thread) and chan_obj.parent_id:
                if ("channel", chan_obj.parent_id) in ignores:
                    return True

        # Check standalone roles
        for role_obj in (roles or []):
            rid = role_obj.id if hasattr(role_obj, "id") else role_obj
            if ("role", rid) in ignores:
                return True

        return False

    async def log_event(
        self,
        guild: Guild,
        channel_key: str,
        embed: Embed,
        *,
        actors: Optional[Sequence[Union[Member, User, int]]] = None,
        targets: Optional[Sequence[Union[Member, User, int]]] = None,
        channels: Optional[Sequence[Union[discord.abc.GuildChannel, Thread, int]]] = None,
        roles: Optional[Sequence[Union[Role, int]]] = None,
    ) -> None:
        """Centralized dispatch helper for sending log entries."""
        if not guild:
            return

        config = await self._get_config(guild.id)
        if not config or not config.get("enabled"):
            return

        channel_id_key = f"{channel_key}_channel_id"
        channel_id = config.get(channel_id_key)
        if not channel_id:
            return

        ignores = await self._get_ignores(guild.id)
        if self._is_ignored(ignores, actors=actors, targets=targets, channels=channels, roles=roles):
            return

        target_channel = guild.get_channel(channel_id)
        if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
            return

        # Check send permissions
        perms = target_channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            return

        try:
            await target_channel.send(embed=embed)
        except (discord.Forbidden, discord.NotFound):
            pass
        except discord.HTTPException as err:
            logger.warning(f"[Logging] Failed to send log to #{target_channel.name} in {guild.id}: {err}")

    @example(",log")
    @hybrid_group(
        name="log",
        aliases=["logging", "logger"],
        invoke_without_command=True,
        description="Manage guild logging configuration",
    )
    @has_permissions(administrator=True)
    async def log(self, ctx: Context) -> None:
        """Overview of the current logging setup."""
        config = await self._get_config(ctx.guild.id)
        if not config or (not config.get("category_id") and not config.get("server_channel_id")):
            embed = Embed(
                title="Logging Configuration",
                description=(
                    f"⚠️ Logging is **not configured** in this server.\n\n"
                    f"Run `{ctx.clean_prefix}log aio` to automatically create a private "
                    f"`Logs` category and all 5 dedicated log channels."
                ),
                color=COLORS.warn,
            )
            embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else ctx.bot.user.display_avatar.url)
            return await ctx.send(embed=embed)

        is_enabled = config.get("enabled", False)
        status_text = "🟢 **Enabled**" if is_enabled else "🔴 **Disabled (Paused)**"
        category = ctx.guild.get_channel(config.get("category_id")) if config.get("category_id") else None

        channels_info = []
        for key, name in LOG_CHANNEL_NAMES.items():
            cid = config.get(f"{key}_channel_id")
            channel = ctx.guild.get_channel(cid) if cid else None
            if channel:
                channels_info.append(f"• **{name}**: {channel.mention}")
            else:
                channels_info.append(f"• **{name}**: *not set up — run `{ctx.clean_prefix}log aio`*")

        ignores = await self._get_ignores(ctx.guild.id)
        role_count = sum(1 for t, _ in ignores if t == "role")
        user_count = sum(1 for t, _ in ignores if t == "user")
        chan_count = sum(1 for t, _ in ignores if t == "channel")
        ignores_summary = f"`{role_count}` roles, `{user_count}` users, `{chan_count}` channels"

        embed = Embed(
            title=f"Logging Configuration — {ctx.guild.name}",
            color=COLORS.neutral if is_enabled else COLORS.warn,
        )
        embed.add_field(name="Status", value=status_text, inline=True)
        embed.add_field(name="Category", value=category.name if category else "None", inline=True)
        embed.add_field(name="Ignored Entities", value=ignores_summary, inline=True)
        embed.add_field(name="Configured Channels", value="\n".join(channels_info), inline=False)
        embed.set_footer(text=f"Use {ctx.clean_prefix}log enable / disable to toggle | {ctx.clean_prefix}log aio to reset")
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        return await ctx.send(embed=embed)

    @example(",log aio")
    @log.command(
        name="aio",
        aliases=["setupall", "all"],
        description="Automatically set up all 5 logging channels inside a private category",
    )
    @has_permissions(administrator=True)
    async def log_aio(self, ctx: Context, *, category_name: str = "Logs") -> None:
        """Creates a staff-only Logs category and all 5 dedicated log channels."""
        if not ctx.guild.me.guild_permissions.manage_channels:
            return await ctx.deny("I require the **Manage Channels** permission to create log channels.")

        config = await self._get_config(ctx.guild.id)
        if config and config.get("category_id"):
            existing_cat = ctx.guild.get_channel(config["category_id"])
            if existing_cat:
                view = SetupConfirmationView(self, ctx, category_name)
                embed = Embed(
                    title="Logging Already Configured",
                    description=(
                        f"Logging is already configured in category **{existing_cat.name}**.\n\n"
                        f"Choose an option below:\n"
                        f"• **Relink & Verify**: Verify existing channels and recreate missing ones.\n"
                        f"• **Recreate Fresh**: Delete existing log category & channels and set up fresh.\n"
                        f"• **Cancel**: Abort setup."
                    ),
                    color=COLORS.warn,
                )
                msg = await ctx.send(embed=embed, view=view)
                await view.wait()

                if view.value == "cancel" or view.value is None:
                    return
                elif view.value == "relink":
                    return await self._perform_relink(ctx, config, existing_cat, msg)
                elif view.value == "recreate":
                    # Delete old channels and category if possible
                    try:
                        for key in LOG_CHANNEL_NAMES:
                            cid = config.get(f"{key}_channel_id")
                            if cid:
                                old_c = ctx.guild.get_channel(cid)
                                if old_c:
                                    await old_c.delete(reason="Recreating log setup fresh")
                        await existing_cat.delete(reason="Recreating log setup fresh")
                    except Exception:
                        pass

        # Perform fresh creation
        await self._create_fresh_setup(ctx, category_name)

    async def _create_fresh_setup(self, ctx: Context, category_name: str) -> None:
        """Create category and all 5 channels from scratch."""
        overwrites = {
            ctx.guild.default_role: PermissionOverwrite(view_channel=False),
            ctx.guild.me: PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        category = await ctx.guild.create_category(
            name=category_name,
            overwrites=overwrites,
            reason=f"Logging setup created by {ctx.author}",
        )

        created_channels: Dict[str, TextChannel] = {}
        for key, name in LOG_CHANNEL_NAMES.items():
            chan = await ctx.guild.create_text_channel(
                name=name,
                category=category,
                reason=f"Logging setup created by {ctx.author}",
            )
            created_channels[key] = chan

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO logging_config (
                guild_id, enabled, category_id, server_channel_id,
                member_channel_id, vc_channel_id, moderation_channel_id,
                message_channel_id
            ) VALUES ($1, 1, $2, $3, $4, $5, $6, $7)
            """,
            ctx.guild.id,
            category.id,
            created_channels["server"].id,
            created_channels["member"].id,
            created_channels["vc"].id,
            created_channels["moderation"].id,
            created_channels["message"].id,
        )
        self._invalidate_cache(ctx.guild.id)

        lines = [f"• **{name}**: {created_channels[key].mention}" for key, name in LOG_CHANNEL_NAMES.items()]
        embed = Embed(
            title=f"{EMOJIS.APPROVE} Logging Configured Successfully",
            description=(
                f"Created category **{category.name}** (hidden from `@everyone`) with 5 dedicated log channels:\n\n"
                + "\n".join(lines)
                + "\n\n"
                f"ℹ️ **Note on Member vs Moderation logs:** Manual actions performed directly in Discord's UI "
                f"will appear in {created_channels['member'].mention}, while actions performed via bot commands "
                f"(like `,ban` or `,mute`) will produce rich command entries in {created_channels['moderation'].mention} "
                f"as well as state updates in {created_channels['member'].mention}."
            ),
            color=COLORS.approve,
        )
        await ctx.send(embed=embed)

    async def _perform_relink(
        self,
        ctx: Context,
        config: Dict[str, Any],
        category: CategoryChannel,
        msg: Optional[discord.Message] = None,
    ) -> None:
        """Verify existing channels and recreate missing ones in existing category."""
        relinked_channels: Dict[str, TextChannel] = {}
        recreated_count = 0

        for key, name in LOG_CHANNEL_NAMES.items():
            cid = config.get(f"{key}_channel_id")
            channel = ctx.guild.get_channel(cid) if cid else None
            if not channel or not isinstance(channel, TextChannel):
                channel = await ctx.guild.create_text_channel(
                    name=name,
                    category=category,
                    reason=f"Repaired missing log channel by {ctx.author}",
                )
                recreated_count += 1
            relinked_channels[key] = channel

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO logging_config (
                guild_id, enabled, category_id, server_channel_id,
                member_channel_id, vc_channel_id, moderation_channel_id,
                message_channel_id
            ) VALUES ($1, 1, $2, $3, $4, $5, $6, $7)
            """,
            ctx.guild.id,
            category.id,
            relinked_channels["server"].id,
            relinked_channels["member"].id,
            relinked_channels["vc"].id,
            relinked_channels["moderation"].id,
            relinked_channels["message"].id,
        )
        self._invalidate_cache(ctx.guild.id)

        lines = [f"• **{name}**: {relinked_channels[key].mention}" for key, name in LOG_CHANNEL_NAMES.items()]
        embed = Embed(
            title=f"{EMOJIS.APPROVE} Logging Re-verified & Relinked",
            description=(
                f"Relinked category **{category.name}** (`{recreated_count}` channels recreated):\n\n"
                + "\n".join(lines)
            ),
            color=COLORS.approve,
        )
        if msg:
            await msg.edit(embed=embed, view=None)
        else:
            await ctx.send(embed=embed)

    @example(",log enable")
    @log.command(name="enable", description="Enable logging for this server")
    @has_permissions(administrator=True)
    async def log_enable(self, ctx: Context) -> None:
        """Enable logging using existing configured channels."""
        config = await self._get_config(ctx.guild.id)
        if not config or (not config.get("category_id") and not config.get("server_channel_id")):
            return await ctx.deny(f"Logging has not been set up yet. Run `{ctx.clean_prefix}log aio` first.")

        await self.bot.pool.execute(
            "UPDATE logging_config SET enabled = 1 WHERE guild_id = $1",
            ctx.guild.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve("Logging has been **enabled**.")

    @example(",log disable")
    @log.command(name="disable", description="Pause logging for this server without deleting setup")
    @has_permissions(administrator=True)
    async def log_disable(self, ctx: Context) -> None:
        """Soft pause logging for this server."""
        config = await self._get_config(ctx.guild.id)
        if not config or (not config.get("category_id") and not config.get("server_channel_id")):
            return await ctx.deny(f"Logging has not been set up yet. Run `{ctx.clean_prefix}log aio` first.")

        await self.bot.pool.execute(
            "UPDATE logging_config SET enabled = 0 WHERE guild_id = $1",
            ctx.guild.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve("Logging has been **disabled** (soft pause). Run `,log enable` to resume.")

    @example(",log repair")
    @log.command(name="repair", description="Recreate any deleted or missing log channels")
    @has_permissions(administrator=True)
    async def log_repair(self, ctx: Context) -> None:
        """Check all 5 log channels and recreate any that were deleted."""
        if not ctx.guild.me.guild_permissions.manage_channels:
            return await ctx.deny("I require the **Manage Channels** permission to repair log channels.")

        config = await self._get_config(ctx.guild.id)
        if not config or not config.get("category_id"):
            return await ctx.deny(f"Logging has not been configured yet. Run `{ctx.clean_prefix}log aio` first.")

        category = ctx.guild.get_channel(config["category_id"])
        if not category or not isinstance(category, CategoryChannel):
            overwrites = {
                ctx.guild.default_role: PermissionOverwrite(view_channel=False),
                ctx.guild.me: PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    attach_files=True,
                    read_message_history=True,
                    manage_channels=True,
                ),
            }
            category = await ctx.guild.create_category(
                name="Logs",
                overwrites=overwrites,
                reason=f"Repaired missing Logs category by {ctx.author}",
            )

        await self._perform_relink(ctx, config, category)

    async def _show_ignore_list(self, ctx: Context) -> None:
        """Helper to render paginated ignore list."""
        ignores = await self._get_ignores(ctx.guild.id)
        if not ignores:
            return await ctx.warn("There are no **ignored** roles, users, or channels in this server.")

        roles_list: List[str] = []
        users_list: List[str] = []
        chans_list: List[str] = []

        for target_type, target_id in sorted(ignores):
            if target_type == "role":
                role = ctx.guild.get_role(target_id)
                roles_list.append(f"• {role.mention} (`{target_id}`)" if role else f"• Unknown Role (`{target_id}`)")
            elif target_type == "user":
                user = ctx.guild.get_member(target_id) or self.bot.get_user(target_id)
                users_list.append(f"• {user.mention} (`{target_id}`)" if user else f"• Unknown User (`{target_id}`)")
            elif target_type == "channel":
                chan = ctx.guild.get_channel(target_id)
                chans_list.append(f"• {chan.mention} (`{target_id}`)" if chan else f"• Unknown Channel (`{target_id}`)")

        all_lines: List[str] = []
        if roles_list:
            all_lines.append(f"**Ignored Roles ({len(roles_list)})**\n" + "\n".join(roles_list))
        if users_list:
            all_lines.append(f"**Ignored Users ({len(users_list)})**\n" + "\n".join(users_list))
        if chans_list:
            all_lines.append(f"**Ignored Channels ({len(chans_list)})**\n" + "\n".join(chans_list))

        pages: List[Embed] = []
        chunk_size = 10
        raw_items: List[str] = []
        if roles_list:
            raw_items.extend([f"🎭 [Role] {r}" for r in roles_list])
        if users_list:
            raw_items.extend([f"👤 [User] {u}" for u in users_list])
        if chans_list:
            raw_items.extend([f"💬 [Channel] {c}" for c in chans_list])

        for i in range(0, len(raw_items), chunk_size):
            chunk = raw_items[i : i + chunk_size]
            emb = Embed(
                title=f"Logging Ignores — {ctx.guild.name}",
                description="\n".join(chunk),
                color=COLORS.neutral,
            )
            emb.set_footer(text=f"Total Ignores: {len(raw_items)} | Page {len(pages) + 1}")
            pages.append(emb)

        if len(pages) == 1:
            return await ctx.send(embed=pages[0])

        paginator = Paginator(self.bot, pages, ctx)
        await paginator.start()

    @example(",log ignore role @Staff")
    @log.group(
        name="ignore",
        invoke_without_command=True,
        description="Ignore a role, user, or channel from logging",
    )
    @has_permissions(administrator=True)
    async def log_ignore(self, ctx: Context) -> None:
        """Subcommands to ignore roles, users, or channels."""
        return await ctx.send_help(ctx.command)

    @example(",log ignore role @Staff")
    @log_ignore.command(name="role", aliases=["r"], description="Ignore a role from all logging")
    @has_permissions(administrator=True)
    async def ignore_role(self, ctx: Context, *, role: Role) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("role", role.id) in ignores:
            return await ctx.warn(f"{role.mention} is **already ignored**.")

        await self.bot.pool.execute(
            "INSERT INTO logging_ignores (guild_id, target_type, target_id) VALUES ($1, 'role', $2)",
            ctx.guild.id,
            role.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Now **ignoring** role {role.mention} from logging.")

    @example(",log ignore user @voby")
    @log_ignore.command(name="user", aliases=["u", "member", "m"], description="Ignore a user from all logging")
    @has_permissions(administrator=True)
    async def ignore_user(self, ctx: Context, *, user: Union[Member, User]) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("user", user.id) in ignores:
            return await ctx.warn(f"{user.mention} is **already ignored**.")

        await self.bot.pool.execute(
            "INSERT INTO logging_ignores (guild_id, target_type, target_id) VALUES ($1, 'user', $2)",
            ctx.guild.id,
            user.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Now **ignoring** user {user.mention} from logging.")

    @example(",log ignore channel #general")
    @log_ignore.command(name="channel", aliases=["c", "ch"], description="Ignore a channel from message/vc logging")
    @has_permissions(administrator=True)
    async def ignore_channel(self, ctx: Context, *, channel: Union[TextChannel, VoiceChannel, StageChannel, Thread]) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("channel", channel.id) in ignores:
            return await ctx.warn(f"{channel.mention} is **already ignored**.")

        await self.bot.pool.execute(
            "INSERT INTO logging_ignores (guild_id, target_type, target_id) VALUES ($1, 'channel', $2)",
            ctx.guild.id,
            channel.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Now **ignoring** channel {channel.mention} from logging.")

    @example(",log ignore list")
    @log_ignore.command(name="list", aliases=["show", "view"], description="List all ignored roles, users, and channels")
    @has_permissions(administrator=True)
    async def ignore_list(self, ctx: Context) -> None:
        return await self._show_ignore_list(ctx)

    @example(",log unignore role @Staff")
    @log.group(
        name="unignore",
        invoke_without_command=True,
        description="Remove a role, user, or channel from logging ignores",
    )
    @has_permissions(administrator=True)
    async def log_unignore(self, ctx: Context) -> None:
        """Subcommands to unignore roles, users, or channels."""
        return await ctx.send_help(ctx.command)

    @example(",log unignore role @Staff")
    @log_unignore.command(name="role", aliases=["r"], description="Stop ignoring a role from logging")
    @has_permissions(administrator=True)
    async def unignore_role(self, ctx: Context, *, role: Role) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("role", role.id) not in ignores:
            return await ctx.warn(f"{role.mention} is **not** in the ignore list.")

        await self.bot.pool.execute(
            "DELETE FROM logging_ignores WHERE guild_id = $1 AND target_type = 'role' AND target_id = $2",
            ctx.guild.id,
            role.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Stopped **ignoring** role {role.mention}.")

    @example(",log unignore user @voby")
    @log_unignore.command(name="user", aliases=["u", "member", "m"], description="Stop ignoring a user from logging")
    @has_permissions(administrator=True)
    async def unignore_user(self, ctx: Context, *, user: Union[Member, User]) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("user", user.id) not in ignores:
            return await ctx.warn(f"{user.mention} is **not** in the ignore list.")

        await self.bot.pool.execute(
            "DELETE FROM logging_ignores WHERE guild_id = $1 AND target_type = 'user' AND target_id = $2",
            ctx.guild.id,
            user.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Stopped **ignoring** user {user.mention}.")

    @example(",log unignore channel #general")
    @log_unignore.command(name="channel", aliases=["c", "ch"], description="Stop ignoring a channel from logging")
    @has_permissions(administrator=True)
    async def unignore_channel(self, ctx: Context, *, channel: Union[TextChannel, VoiceChannel, StageChannel, Thread]) -> None:
        ignores = await self._get_ignores(ctx.guild.id)
        if ("channel", channel.id) not in ignores:
            return await ctx.warn(f"{channel.mention} is **not** in the ignore list.")

        await self.bot.pool.execute(
            "DELETE FROM logging_ignores WHERE guild_id = $1 AND target_type = 'channel' AND target_id = $2",
            ctx.guild.id,
            channel.id,
        )
        self._invalidate_cache(ctx.guild.id)
        return await ctx.approve(f"Stopped **ignoring** channel {channel.mention}.")

    @example(",log unignore list")
    @log_unignore.command(name="list", aliases=["show", "view"], description="List all ignored roles, users, and channels")
    @has_permissions(administrator=True)
    async def unignore_list(self, ctx: Context) -> None:
        return await self._show_ignore_list(ctx)

    # =========================================================================
    # 1. SERVER-LOGS LISTENERS
    # =========================================================================

    @Cog.listener("on_guild_update")
    async def server_update_listener(self, before: Guild, after: Guild) -> None:
        """Log changes to server name, icon, banner, splash, description, verification, tier."""
        changes: List[str] = []

        if before.name != after.name:
            changes.append(f"• **Name**: `{before.name}` ➔ `{after.name}`")
        if before.description != after.description:
            old_desc = f"`{before.description}`" if before.description else "*None*"
            new_desc = f"`{after.description}`" if after.description else "*None*"
            changes.append(f"• **Description**: {old_desc} ➔ {new_desc}")
        if before.verification_level != after.verification_level:
            changes.append(f"• **Verification**: `{before.verification_level.name}` ➔ `{after.verification_level.name}`")
        if before.premium_tier != after.premium_tier:
            changes.append(f"• **Boost Tier**: `Level {before.premium_tier}` ➔ `Level {after.premium_tier}`")
        if before.vanity_url_code != after.vanity_url_code:
            changes.append(f"• **Vanity Code**: `{before.vanity_url_code}` ➔ `{after.vanity_url_code}`")
        if before.icon != after.icon:
            old_icon = f"[Link]({before.icon.url})" if before.icon else "*None*"
            new_icon = f"[Link]({after.icon.url})" if after.icon else "*None*"
            changes.append(f"• **Icon**: {old_icon} ➔ {new_icon}")
        if before.banner != after.banner:
            old_banner = f"[Link]({before.banner.url})" if before.banner else "*None*"
            new_banner = f"[Link]({after.banner.url})" if after.banner else "*None*"
            changes.append(f"• **Banner**: {old_banner} ➔ {new_banner}")
        if before.splash != after.splash:
            old_splash = f"[Link]({before.splash.url})" if before.splash else "*None*"
            new_splash = f"[Link]({after.splash.url})" if after.splash else "*None*"
            changes.append(f"• **Splash**: {old_splash} ➔ {new_splash}")

        if not changes:
            return

        entry = await self.get_audit_entry(after, discord.AuditLogAction.guild_update)
        moderator = entry.user if entry else None

        embed = Embed(
            title="⚙️ Server Settings Updated",
            description="\n".join(changes),
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )
        if moderator:
            embed.add_field(name="Updated By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
        if after.icon:
            embed.set_thumbnail(url=after.icon.url)

        await self.log_event(after, "server", embed, actors=[moderator] if moderator else None)

    @Cog.listener("on_guild_emojis_update")
    async def server_emojis_listener(
        self, guild: Guild, before: Sequence[Emoji], after: Sequence[Emoji]
    ) -> None:
        """Log emoji additions, removals, and renames."""
        before_map = {e.id: e for e in before}
        after_map = {e.id: e for e in after}

        added = [e for e in after if e.id not in before_map]
        removed = [e for e in before if e.id not in after_map]
        renamed = [
            (before_map[e.id], e)
            for e in after
            if e.id in before_map and before_map[e.id].name != e.name
        ]

        if not added and not removed and not renamed:
            return

        embed = Embed(
            title="😀 Server Emojis Updated",
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )

        moderator: Optional[Union[Member, User]] = None

        if added:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.emoji_create)
            if entry and entry.user:
                moderator = entry.user
            added_lines = [f"{e} `:{e.name}:` (`{e.id}`)" for e in added[:15]]
            if len(added) > 15:
                added_lines.append(f"*...and {len(added) - 15} more*")
            embed.add_field(name=f"Added Emojis ({len(added)})", value="\n".join(added_lines), inline=False)

        if removed:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.emoji_delete)
            if entry and entry.user:
                moderator = entry.user
            removed_lines = [f"`:{e.name}:` (`{e.id}`)" for e in removed[:15]]
            if len(removed) > 15:
                removed_lines.append(f"*...and {len(removed) - 15} more*")
            embed.add_field(name=f"Removed Emojis ({len(removed)})", value="\n".join(removed_lines), inline=False)

        if renamed:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.emoji_update)
            if entry and entry.user:
                moderator = entry.user
            renamed_lines = [f"{curr} `:{old.name}:` ➔ `:{curr.name}:`" for old, curr in renamed[:15]]
            embed.add_field(name=f"Renamed Emojis ({len(renamed)})", value="\n".join(renamed_lines), inline=False)

        if moderator:
            embed.add_field(name="Action By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)

        await self.log_event(guild, "server", embed, actors=[moderator] if moderator else None)

    @Cog.listener("on_guild_stickers_update")
    async def server_stickers_listener(
        self, guild: Guild, before: Sequence[GuildSticker], after: Sequence[GuildSticker]
    ) -> None:
        """Log sticker additions, removals, and renames."""
        before_map = {s.id: s for s in before}
        after_map = {s.id: s for s in after}

        added = [s for s in after if s.id not in before_map]
        removed = [s for s in before if s.id not in after_map]
        renamed = [
            (before_map[s.id], s)
            for s in after
            if s.id in before_map and before_map[s.id].name != s.name
        ]

        if not added and not removed and not renamed:
            return

        embed = Embed(
            title="🏷️ Server Stickers Updated",
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )

        moderator: Optional[Union[Member, User]] = None

        if added:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.sticker_create)
            if entry and entry.user:
                moderator = entry.user
            lines = [f"• **{s.name}** (`{s.id}`)" for s in added[:15]]
            embed.add_field(name=f"Added Stickers ({len(added)})", value="\n".join(lines), inline=False)

        if removed:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.sticker_delete)
            if entry and entry.user:
                moderator = entry.user
            lines = [f"• **{s.name}** (`{s.id}`)" for s in removed[:15]]
            embed.add_field(name=f"Removed Stickers ({len(removed)})", value="\n".join(lines), inline=False)

        if renamed:
            lines = [f"• `{old.name}` ➔ `{curr.name}` (`{curr.id}`)" for old, curr in renamed[:15]]
            embed.add_field(name=f"Renamed Stickers ({len(renamed)})", value="\n".join(lines), inline=False)

        if moderator:
            embed.add_field(name="Action By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)

        await self.log_event(guild, "server", embed, actors=[moderator] if moderator else None)

    # =========================================================================
    # 2. MEMBER-LOGS LISTENERS
    # =========================================================================

    @Cog.listener("on_member_join")
    async def member_join_listener(self, member: Member) -> None:
        """Log new member joins."""
        created_ts = int(member.created_at.timestamp())
        embed = Embed(
            title="📥 Member Joined",
            description=f"{member.mention} (`{member.name}`)",
            color=COLORS.approve,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Account Created", value=f"<t:{created_ts}:F> (<t:{created_ts}:R>)", inline=False)
        embed.add_field(name="Member Count", value=f"`{member.guild.member_count}`", inline=True)
        embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)

        await self.log_event(member.guild, "member", embed, targets=[member])

    @Cog.listener("on_member_remove")
    async def member_remove_listener(self, member: Member) -> None:
        """Log member departures, detecting kicks and bans via audit logs."""
        kick_entry = await self.get_audit_entry(member.guild, discord.AuditLogAction.kick, target_id=member.id)
        ban_entry = await self.get_audit_entry(member.guild, discord.AuditLogAction.ban, target_id=member.id)

        joined_ts = int(member.joined_at.timestamp()) if member.joined_at else None
        created_ts = int(member.created_at.timestamp())

        if kick_entry:
            title = "👢 Member Kicked"
            moderator = kick_entry.user
            reason = kick_entry.reason or "No reason specified"
            actor = moderator
        elif ban_entry:
            title = "🔨 Member Banned & Removed"
            moderator = ban_entry.user
            reason = ban_entry.reason or "No reason specified"
            actor = moderator
        else:
            title = "📤 Member Left"
            moderator = None
            reason = None
            actor = None

        embed = Embed(
            title=title,
            description=f"{member.mention} (`{member.name}`)",
            color=COLORS.deny,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Member Count", value=f"`{member.guild.member_count}`", inline=True)
        if joined_ts:
            embed.add_field(name="Joined Server", value=f"<t:{joined_ts}:R>", inline=False)
        embed.add_field(name="Account Created", value=f"<t:{created_ts}:R>", inline=False)

        roles = [r.mention for r in member.roles if not r.is_default()]
        if roles:
            roles_str = ", ".join(roles[:12])
            if len(roles) > 12:
                roles_str += f" *and {len(roles) - 12} more*"
            embed.add_field(name="Roles Held", value=roles_str, inline=False)

        if moderator:
            embed.add_field(name="Action By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
            embed.add_field(name="Reason", value=f"`{reason}`", inline=True)

        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log_event(member.guild, "member", embed, targets=[member], actors=[actor] if actor else None)

    @Cog.listener("on_member_ban")
    async def member_ban_listener(self, guild: Guild, user: Union[User, Member]) -> None:
        """Log raw gateway member ban event."""
        entry = await self.get_audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        moderator = entry.user if entry else None
        reason = entry.reason if entry and entry.reason else "No reason specified"

        embed = Embed(
            title="🔨 Member Banned",
            description=f"{user.mention} (`{user.name}`)",
            color=COLORS.deny,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
        if moderator:
            embed.add_field(name="Banned By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)

        await self.log_event(guild, "member", embed, targets=[user], actors=[moderator] if moderator else None)

    @Cog.listener("on_member_unban")
    async def member_unban_listener(self, guild: Guild, user: User) -> None:
        """Log member unban event."""
        entry = await self.get_audit_entry(guild, discord.AuditLogAction.unban, target_id=user.id)
        moderator = entry.user if entry else None
        reason = entry.reason if entry and entry.reason else "No reason specified"

        embed = Embed(
            title="🔓 Member Unbanned",
            description=f"{user.mention} (`{user.name}`)",
            color=COLORS.approve,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
        if moderator:
            embed.add_field(name="Unbanned By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)

        await self.log_event(guild, "member", embed, targets=[user], actors=[moderator] if moderator else None)

    @Cog.listener("on_member_update")
    async def member_update_listener(self, before: Member, after: Member) -> None:
        """Log member role changes, nickname changes, and timeouts."""
        guild = after.guild

        # 1. Timeout changes
        if before.timed_out_until != after.timed_out_until:
            now = datetime.now(timezone.utc)
            if after.timed_out_until and after.timed_out_until > now:
                # Member timed out
                entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_update, target_id=after.id)
                moderator = entry.user if entry else None
                reason = entry.reason if entry and entry.reason else "No reason specified"
                until_ts = int(after.timed_out_until.timestamp())

                embed = Embed(
                    title="⏳ Member Timed Out",
                    description=f"{after.mention} (`{after.name}`)",
                    color=COLORS.deny,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Timed Out Until", value=f"<t:{until_ts}:F> (<t:{until_ts}:R>)", inline=False)
                if moderator:
                    embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
                embed.add_field(name="Reason", value=f"`{reason}`", inline=True)
                embed.set_thumbnail(url=after.display_avatar.url)

                await self.log_event(guild, "member", embed, targets=[after], actors=[moderator] if moderator else None)
            elif before.timed_out_until and not after.timed_out_until:
                # Timeout removed
                entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_update, target_id=after.id)
                moderator = entry.user if entry else None

                embed = Embed(
                    title="🔊 Member Timeout Removed",
                    description=f"{after.mention} (`{after.name}`)",
                    color=COLORS.approve,
                    timestamp=datetime.now(timezone.utc),
                )
                if moderator:
                    embed.add_field(name="Removed By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
                embed.set_thumbnail(url=after.display_avatar.url)

                await self.log_event(guild, "member", embed, targets=[after], actors=[moderator] if moderator else None)

        # 2. Role changes
        if before.roles != after.roles:
            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]

            if added_roles or removed_roles:
                entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_role_update, target_id=after.id)
                moderator = entry.user if entry else None

                embed = Embed(
                    title="🎭 Member Roles Updated",
                    description=f"{after.mention} (`{after.name}`)",
                    color=COLORS.neutral,
                    timestamp=datetime.now(timezone.utc),
                )
                if added_roles:
                    roles_str = ", ".join([r.mention for r in added_roles])
                    embed.add_field(name="Roles Added", value=roles_str, inline=False)
                if removed_roles:
                    roles_str = ", ".join([r.mention for r in removed_roles])
                    embed.add_field(name="Roles Removed", value=roles_str, inline=False)
                if moderator:
                    embed.add_field(name="Updated By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)

                embed.set_thumbnail(url=after.display_avatar.url)
                await self.log_event(
                    guild,
                    "member",
                    embed,
                    targets=[after],
                    actors=[moderator] if moderator else None,
                    roles=added_roles + removed_roles,
                )

        # 3. Nickname changes
        if before.nick != after.nick:
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_update, target_id=after.id)
            moderator = entry.user if entry else None

            old_nick = f"`{before.nick}`" if before.nick else "*None (Username)*"
            new_nick = f"`{after.nick}`" if after.nick else "*None (Reset)*"

            embed = Embed(
                title="📝 Member Nickname Changed",
                description=f"{after.mention} (`{after.name}`)",
                color=COLORS.neutral,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Old Nickname", value=old_nick, inline=True)
            embed.add_field(name="New Nickname", value=new_nick, inline=True)
            if moderator:
                embed.add_field(name="Changed By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)
            embed.set_thumbnail(url=after.display_avatar.url)

            await self.log_event(guild, "member", embed, targets=[after], actors=[moderator] if moderator else None)

        # 4. Guild Avatar change
        if before.guild_avatar != after.guild_avatar:
            embed = Embed(
                title="🖼️ Guild Avatar Changed",
                description=f"{after.mention} (`{after.name}`)",
                color=COLORS.neutral,
                timestamp=datetime.now(timezone.utc),
            )
            old_av = f"[Old Avatar]({before.guild_avatar.url})" if before.guild_avatar else "*Default Avatar*"
            new_av = f"[New Avatar]({after.guild_avatar.url})" if after.guild_avatar else "*Default Avatar*"
            embed.add_field(name="Avatar Links", value=f"{old_av} ➔ {new_av}", inline=False)
            embed.set_thumbnail(url=after.display_avatar.url)

            await self.log_event(guild, "member", embed, targets=[after])

    @Cog.listener("on_user_update")
    async def user_update_listener(self, before: User, after: User) -> None:
        """Log global username or global avatar changes for mutual guilds."""
        name_changed = before.name != after.name
        avatar_changed = before.avatar != after.avatar

        if not name_changed and not avatar_changed:
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if not member:
                continue

            embed = Embed(
                title="👤 User Profile Updated",
                description=f"{member.mention} (`{after.name}`)",
                color=COLORS.neutral,
                timestamp=datetime.now(timezone.utc),
            )
            if name_changed:
                embed.add_field(name="Username Changed", value=f"`{before.name}` ➔ `{after.name}`", inline=False)
            if avatar_changed:
                old_av = f"[Old Avatar]({before.display_avatar.url})"
                new_av = f"[New Avatar]({after.display_avatar.url})"
                embed.add_field(name="Global Avatar", value=f"{old_av} ➔ {new_av}", inline=False)

            embed.set_thumbnail(url=after.display_avatar.url)
            await self.log_event(guild, "member", embed, targets=[member])

    # =========================================================================
    # 3. VC-LOGS LISTENERS
    # =========================================================================

    @Cog.listener("on_voice_state_update")
    async def voice_state_listener(
        self, member: Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Log voice channel join, leave, move, and server mute/deafen toggles."""
        guild = member.guild

        # 1. Voice channel transition
        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                # Joined VC
                embed = Embed(
                    title="🔊 Voice Channel Joined",
                    description=f"{member.mention} (`{member.name}`) joined {after.channel.mention}",
                    color=COLORS.approve,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Channel", value=f"`{after.channel.name}` (`{after.channel.id}`)", inline=True)
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
                embed.set_thumbnail(url=member.display_avatar.url)
                await self.log_event(guild, "vc", embed, targets=[member], channels=[after.channel])

            elif before.channel is not None and after.channel is None:
                # Left VC
                embed = Embed(
                    title="🔈 Voice Channel Left",
                    description=f"{member.mention} (`{member.name}`) left `{before.channel.name}`",
                    color=COLORS.deny,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Channel", value=f"`{before.channel.name}` (`{before.channel.id}`)", inline=True)
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
                embed.set_thumbnail(url=member.display_avatar.url)
                await self.log_event(guild, "vc", embed, targets=[member], channels=[before.channel])

            elif before.channel is not None and after.channel is not None:
                # Moved VC
                embed = Embed(
                    title="🔀 Voice Channel Moved",
                    description=f"{member.mention} (`{member.name}`) moved voice channels",
                    color=COLORS.neutral,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="From", value=f"`{before.channel.name}` (`{before.channel.id}`)", inline=True)
                embed.add_field(name="To", value=f"{after.channel.mention} (`{after.channel.id}`)", inline=True)
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=False)
                embed.set_thumbnail(url=member.display_avatar.url)
                await self.log_event(guild, "vc", embed, targets=[member], channels=[before.channel, after.channel])

        # 2. Server mute toggles
        if before.mute != after.mute:
            status = "Server Muted" if after.mute else "Server Unmuted"
            color = COLORS.deny if after.mute else COLORS.approve
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_update, target_id=member.id)
            moderator = entry.user if entry else None

            embed = Embed(
                title=f"🎙️ Member {status}",
                description=f"{member.mention} (`{member.name}`) was {status.lower()}",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
            if moderator:
                embed.add_field(name="Action By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            channel = after.channel or before.channel
            await self.log_event(
                guild,
                "vc",
                embed,
                targets=[member],
                actors=[moderator] if moderator else None,
                channels=[channel] if channel else None,
            )

        # 3. Server deafen toggles
        if before.deaf != after.deaf:
            status = "Server Deafened" if after.deaf else "Server Undeafened"
            color = COLORS.deny if after.deaf else COLORS.approve
            entry = await self.get_audit_entry(guild, discord.AuditLogAction.member_update, target_id=member.id)
            moderator = entry.user if entry else None

            embed = Embed(
                title=f"🔇 Member {status}",
                description=f"{member.mention} (`{member.name}`) was {status.lower()}",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
            if moderator:
                embed.add_field(name="Action By", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            channel = after.channel or before.channel
            await self.log_event(
                guild,
                "vc",
                embed,
                targets=[member],
                actors=[moderator] if moderator else None,
                channels=[channel] if channel else None,
            )

    @Cog.listener("on_guild_channel_update")
    async def voice_channel_settings_listener(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        """Log voice channel setting changes (bitrate, user limit, name, region)."""
        if not isinstance(after, (VoiceChannel, StageChannel)):
            return

        changes: List[str] = []
        if before.name != after.name:
            changes.append(f"• **Name**: `{before.name}` ➔ `{after.name}`")
        if getattr(before, "bitrate", None) != getattr(after, "bitrate", None):
            changes.append(f"• **Bitrate**: `{before.bitrate // 1000}kbps` ➔ `{after.bitrate // 1000}kbps`")
        if getattr(before, "user_limit", None) != getattr(after, "user_limit", None):
            old_lim = f"`{before.user_limit}`" if before.user_limit else "*Unlimited*"
            new_lim = f"`{after.user_limit}`" if after.user_limit else "*Unlimited*"
            changes.append(f"• **User Limit**: {old_lim} ➔ {new_lim}")
        if getattr(before, "rtc_region", None) != getattr(after, "rtc_region", None):
            changes.append(f"• **Region**: `{before.rtc_region or 'Automatic'}` ➔ `{after.rtc_region or 'Automatic'}`")

        if not changes:
            return

        entry = await self.get_audit_entry(after.guild, discord.AuditLogAction.channel_update, target_id=after.id)
        moderator = entry.user if entry else None

        embed = Embed(
            title="⚙️ Voice Channel Settings Updated",
            description=f"{after.mention} (`{after.name}`)\n\n" + "\n".join(changes),
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )
        if moderator:
            embed.add_field(name="Updated By", value=f"{moderator.mention} (`{moderator.id}`)", inline=False)

        await self.log_event(
            after.guild,
            "vc",
            embed,
            channels=[after],
            actors=[moderator] if moderator else None,
        )

    # =========================================================================
    # 4. MODERATION-LOGS LISTENERS & DISPATCH
    # =========================================================================

    @Cog.listener("on_moderation_action")
    async def on_moderation_action_listener(
        self,
        guild: Guild,
        action: str,
        moderator: Union[Member, User],
        target: Union[Member, User, discord.abc.GuildChannel, Role, str],
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle moderation action event dispatched from bot commands."""
        await self.handle_moderation_action(
            guild=guild,
            action=action,
            moderator=moderator,
            target=target,
            reason=reason,
            duration=duration,
            extra=extra or {},
        )

    async def handle_moderation_action(
        self,
        guild: Guild,
        action: str,
        moderator: Union[Member, User],
        target: Union[Member, User, discord.abc.GuildChannel, Role, str],
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Construct and send rich moderation command log entry."""
        action_emojis = {
            "Ban": ("🔨", COLORS.deny),
            "Kick": ("👢", COLORS.deny),
            "Timeout": ("⏳", COLORS.deny),
            "Untimeout": ("🔊", COLORS.approve),
            "Unban": ("🔓", COLORS.approve),
            "Warn": ("⚠️", COLORS.warn),
            "Warns Cleared": ("⚠️", COLORS.approve),
            "Forced Nickname": ("🏷️", COLORS.neutral),
            "Strip Staff": ("🛡️", COLORS.deny),
            "Image Mute": ("🔇", COLORS.deny),
            "Image Unmute": ("🔊", COLORS.approve),
            "Reaction Mute": ("😶", COLORS.deny),
            "Reaction Unmute": ("😀", COLORS.approve),
        }

        emoji, color = action_emojis.get(action, ("🛡️", COLORS.neutral))

        embed = Embed(
            title=f"{emoji} Moderation Action: {action}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        # Target formatting
        if hasattr(target, "mention"):
            target_str = f"{target.mention} (`{target.name}` | `{target.id}`)"
            target_obj = target
        else:
            target_str = str(target)
            target_obj = None

        embed.add_field(name="Target", value=target_str, inline=False)
        embed.add_field(
            name="Moderator",
            value=f"{moderator.mention} (`{moderator.name}` | `{moderator.id}`)",
            inline=False,
        )

        if duration:
            embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        if extra and "total_warns" in extra:
            embed.add_field(name="Total Warnings", value=f"`{extra['total_warns']}`", inline=True)

        embed.add_field(name="Reason", value=f"`{reason or 'No reason provided.'}`", inline=False)

        if hasattr(target, "display_avatar"):
            embed.set_thumbnail(url=target.display_avatar.url)

        await self.log_event(
            guild,
            "moderation",
            embed,
            actors=[moderator],
            targets=[target_obj] if target_obj else None,
        )

    # =========================================================================
    # 5. MESSAGE-LOGS LISTENERS
    # =========================================================================

    @Cog.listener("on_message")
    async def message_send_listener(self, message: discord.Message) -> None:
        """Log message sends ONLY when the message is not plain text.

        Avoids feedback loops by ignoring all bot messages (including own log embeds).
        """
        if not message.guild or message.author.bot:
            return

        # Store in raw message cache for delete/edit tracking
        record_raw_message(message)

        # "Not plain text" filter check:
        # A message is logged on send ONLY if it has attachments, stickers, polls, or embeds.
        has_attachments = bool(message.attachments)
        has_stickers = bool(getattr(message, "stickers", None))
        has_poll = bool(getattr(message, "poll", None))
        has_embeds = bool(message.embeds)

        if not (has_attachments or has_stickers or has_poll or has_embeds):
            # Plain text message — do NOT log on send
            return

        embed = Embed(
            title="📎 Message Sent (Media / Special Content)",
            description=f"Sent by {message.author.mention} in {message.channel.mention} • [Jump to Message]({message.jump_url})",
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )

        if message.content:
            text_preview = message.content[:1000] + ("..." if len(message.content) > 1000 else "")
            embed.add_field(name="Text Content", value=text_preview, inline=False)

        if has_attachments:
            att_lines = [f"• [{a.filename}]({a.url}) (`{a.size // 1024} KB`)" for a in message.attachments[:10]]
            embed.add_field(name=f"Attachments ({len(message.attachments)})", value="\n".join(att_lines), inline=False)
            if any(a.content_type and a.content_type.startswith("image") for a in message.attachments):
                for a in message.attachments:
                    if a.content_type and a.content_type.startswith("image"):
                        embed.set_image(url=a.url)
                        break

        if has_stickers:
            stk_lines = [f"• **{s.name}** (`{s.id}`)" for s in message.stickers]
            embed.add_field(name="Stickers", value="\n".join(stk_lines), inline=False)

        if has_poll:
            poll = message.poll
            poll_question = poll.question.text if hasattr(poll.question, "text") else str(poll.question)
            embed.add_field(name="📊 Poll Question", value=f"`{poll_question}`", inline=False)

        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id} | Message ID: {message.id}")

        await self.log_event(
            message.guild,
            "message",
            embed,
            actors=[message.author],
            channels=[message.channel],
        )

    @Cog.listener("on_message_delete")
    async def message_delete_listener(self, message: discord.Message) -> None:
        """Log deleted messages."""
        if not message.guild or message.author.bot:
            return

        embed = Embed(
            title="🗑️ Message Deleted",
            description=f"Message by {message.author.mention} deleted in {message.channel.mention}",
            color=COLORS.deny,
            timestamp=datetime.now(timezone.utc),
        )

        content = message.content or "*No text content*"
        if len(content) > 1000:
            content = content[:1000] + "..."
        embed.add_field(name="Content", value=content, inline=False)

        if message.attachments:
            att_lines = [f"• [{a.filename}]({a.url})" for a in message.attachments[:10]]
            embed.add_field(name=f"Attachments ({len(message.attachments)})", value="\n".join(att_lines), inline=False)
            if any(a.content_type and a.content_type.startswith("image") for a in message.attachments):
                for a in message.attachments:
                    if a.content_type and a.content_type.startswith("image"):
                        embed.set_image(url=a.url)
                        break

        created_ts = int(message.created_at.timestamp())
        embed.add_field(name="Sent At", value=f"<t:{created_ts}:R>", inline=True)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id} | Message ID: {message.id}")

        await self.log_event(
            message.guild,
            "message",
            embed,
            actors=[message.author],
            channels=[message.channel],
        )

    @Cog.listener("on_raw_message_delete")
    async def raw_message_delete_listener(self, payload: discord.RawMessageDeleteEvent) -> None:
        """Fallback for deleted messages not cached by discord.py."""
        if payload.cached_message:
            return  # Handled by on_message_delete

        cached = rawMessageCache.pop(payload.message_id, None)
        if not cached or not cached.get("guild_id"):
            return

        guild = self.bot.get_guild(cached["guild_id"])
        if not guild:
            return

        channel = guild.get_channel(cached["channel_id"])
        if not channel:
            return

        author_id = cached.get("author_id")
        author_name = cached.get("author", "Unknown")
        author_mention = f"<@{author_id}>" if author_id else f"`{author_name}`"

        embed = Embed(
            title="🗑️ Message Deleted (Cached Snapshot)",
            description=f"Message by {author_mention} deleted in {channel.mention}",
            color=COLORS.deny,
            timestamp=datetime.now(timezone.utc),
        )

        content = cached.get("content") or "*No text content*"
        if len(content) > 1000:
            content = content[:1000] + "..."
        embed.add_field(name="Content", value=content, inline=False)

        attachments = cached.get("attachments", [])
        if attachments:
            att_lines = [f"• [Attachment]({url})" for url in attachments[:10]]
            embed.add_field(name=f"Attachments ({len(attachments)})", value="\n".join(att_lines), inline=False)
            if cached.get("image_url"):
                embed.set_image(url=cached["image_url"])

        if cached.get("created_at"):
            created_ts = int(cached["created_at"].timestamp())
            embed.add_field(name="Sent At", value=f"<t:{created_ts}:R>", inline=True)

        if cached.get("author_url"):
            embed.set_thumbnail(url=cached["author_url"])
        embed.set_footer(text=f"User ID: {author_id} | Message ID: {payload.message_id}")

        await self.log_event(
            guild,
            "message",
            embed,
            actors=[author_id] if author_id else None,
            channels=[channel],
        )

    @Cog.listener("on_message_edit")
    async def message_edit_listener(self, before: discord.Message, after: discord.Message) -> None:
        """Log message content edits."""
        if not before.guild or before.author.bot:
            return

        if before.content == after.content:
            # No text content change (e.g. only embeds loaded or pins)
            return

        embed = Embed(
            title="✏️ Message Edited",
            description=f"Message by {after.author.mention} edited in {after.channel.mention} • [Jump to Message]({after.jump_url})",
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )

        before_content = before.content or "*No previous text content*"
        after_content = after.content or "*No new text content*"

        if len(before_content) > 1000:
            before_content = before_content[:1000] + "..."
        if len(after_content) > 1000:
            after_content = after_content[:1000] + "..."

        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After", value=after_content, inline=False)

        created_ts = int(before.created_at.timestamp())
        embed.add_field(name="Originally Sent", value=f"<t:{created_ts}:R>", inline=True)
        embed.set_thumbnail(url=after.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {after.author.id} | Message ID: {after.id}")

        await self.log_event(
            after.guild,
            "message",
            embed,
            actors=[after.author],
            channels=[after.channel],
        )

    @Cog.listener("on_raw_message_edit")
    async def raw_message_edit_listener(self, payload: discord.RawMessageEditEvent) -> None:
        """Fallback for edited messages not cached by discord.py."""
        if payload.cached_message:
            return  # Handled by on_message_edit

        cached = rawMessageCache.get(payload.message_id)
        if not cached or not cached.get("guild_id"):
            return

        new_content = payload.data.get("content")
        old_content = cached.get("content", "")

        if not new_content or new_content == old_content:
            return

        guild = self.bot.get_guild(cached["guild_id"])
        if not guild:
            return

        channel = guild.get_channel(cached["channel_id"])
        if not channel:
            return

        author_id = cached.get("author_id")
        author_name = cached.get("author", "Unknown")
        author_mention = f"<@{author_id}>" if author_id else f"`{author_name}`"
        jump_url = f"https://discord.com/channels/{guild.id}/{channel.id}/{payload.message_id}"

        embed = Embed(
            title="✏️ Message Edited (Cached Snapshot)",
            description=f"Message by {author_mention} edited in {channel.mention} • [Jump to Message]({jump_url})",
            color=COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )

        before_str = old_content or "*No previous text content*"
        after_str = new_content or "*No new text content*"

        if len(before_str) > 1000:
            before_str = before_str[:1000] + "..."
        if len(after_str) > 1000:
            after_str = after_str[:1000] + "..."

        embed.add_field(name="Before", value=before_str, inline=False)
        embed.add_field(name="After", value=after_str, inline=False)

        if cached.get("created_at"):
            created_ts = int(cached["created_at"].timestamp())
            embed.add_field(name="Originally Sent", value=f"<t:{created_ts}:R>", inline=True)

        if cached.get("author_url"):
            embed.set_thumbnail(url=cached["author_url"])
        embed.set_footer(text=f"User ID: {author_id} | Message ID: {payload.message_id}")

        # Update cache snapshot with new content
        cached["content"] = new_content

        await self.log_event(
            guild,
            "message",
            embed,
            actors=[author_id] if author_id else None,
            channels=[channel],
        )
