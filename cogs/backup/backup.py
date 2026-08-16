import asyncio
import aiosqlite
import json
import random
import sqlite3
import string
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import discord
from discord.ext import commands
from loguru import logger

from base.config import COLORS
from base.context import Context
from base.managers.types import CogMeta
from base.Xrypton import SqlitePool

SCHEMA = """
CREATE TABLE IF NOT EXISTS backups (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    source_guild_id INTEGER NOT NULL,
    source_guild_name TEXT NOT NULL,
    name TEXT,
    created_at TIMESTAMP NOT NULL,
    includes_assets BOOLEAN NOT NULL DEFAULT 0,
    channel_count INTEGER,
    role_count INTEGER,
    size_estimate_bytes INTEGER
);

CREATE TABLE IF NOT EXISTS backup_settings (
    backup_id TEXT,
    key TEXT,
    value TEXT
);

CREATE TABLE IF NOT EXISTS backup_roles (
    backup_id TEXT,
    role_index INTEGER,
    name TEXT,
    color INTEGER,
    hoist BOOLEAN,
    mentionable BOOLEAN,
    position INTEGER,
    permissions BIGINT,
    is_managed BOOLEAN
);

CREATE TABLE IF NOT EXISTS backup_categories (
    backup_id TEXT,
    category_index INTEGER,
    name TEXT,
    position INTEGER
);

CREATE TABLE IF NOT EXISTS backup_category_overwrites (
    backup_id TEXT,
    category_index INTEGER,
    target_role_index INTEGER,
    target_is_everyone BOOLEAN,
    allow BIGINT,
    deny BIGINT
);

CREATE TABLE IF NOT EXISTS backup_channels (
    backup_id TEXT,
    channel_index INTEGER,
    category_index INTEGER,
    type TEXT,
    name TEXT,
    position INTEGER,
    topic TEXT,
    nsfw BOOLEAN,
    slowmode_delay INTEGER,
    bitrate INTEGER,
    user_limit INTEGER
);

CREATE TABLE IF NOT EXISTS backup_channel_overwrites (
    backup_id TEXT,
    channel_index INTEGER,
    target_role_index INTEGER,
    target_is_everyone BOOLEAN,
    allow BIGINT,
    deny BIGINT
);

CREATE TABLE IF NOT EXISTS backup_assets (
    backup_id TEXT,
    asset_type TEXT,
    data BLOB
);

CREATE TABLE IF NOT EXISTS backup_jobs (
    job_id TEXT PRIMARY KEY,
    backup_id TEXT,
    guild_id INTEGER,
    user_id INTEGER,
    job_type TEXT,
    status TEXT,
    progress_current INTEGER,
    progress_total INTEGER,
    current_step TEXT,
    started_at TIMESTAMP,
    rollback_data TEXT,
    error_message TEXT
);
"""


CHANNEL_SYMBOLS = {
    "text": "#",
    "announcement": "!",
    "voice": "\N{SPEAKER}",
    "stage": "\N{MICROPHONE}",
    "forum": "\N{BOOKS}",
}


def _b(value) -> bool:
    """Coerce a stored sqlite integer/boolean back into a Python bool."""
    return bool(value)


class AssetPromptView(discord.ui.View):
    """First step of `backup create`: ask whether to include server assets."""

    def __init__(self, cog: "Backup", ctx: Context):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.include = False
        self.timed_out = False
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("You cannot respond to this prompt.", ephemeral=True)
        return False

    @discord.ui.button(label="Include assets", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.include = True
        self.stop()

    @discord.ui.button(label="Skip (recommended)", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.include = False
        self.stop()

    async def on_timeout(self):
        self.timed_out = True
        self.stop()


class ConfirmLoadView(discord.ui.View):
    """Pre-restoration confirmation for `backup load`."""

    def __init__(self, cog: "Backup", ctx: Context, backup: dict, wipe: bool):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.backup = backup
        self.wipe = wipe
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("You cannot confirm this action.", ephemeral=True)
        return False

    @discord.ui.button(label="Confirm Load", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.wipe:
            await interaction.response.send_modal(
                TypeToConfirmModal(self.cog, self.ctx, self.backup, self.wipe, self.message)
            )
        else:
            await self._proceed(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.cog.embed("Load cancelled", "No changes were made."), view=None
        )
        self.stop()

    async def _proceed(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=self.cog.embed("Restore started", "Restoring in the background. Track it with `,backup status`."),
            view=None,
        )
        self.stop()
        await self.cog.run_load(self.ctx, self.backup, self.wipe, self.message)


class TypeToConfirmModal(discord.ui.Modal, title="Type to confirm wipe"):
    """Second, stronger confirmation for the destructive `--wipe` mode."""

    def __init__(self, cog: "Backup", ctx: Context, backup: dict, wipe: bool, confirm_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.ctx = ctx
        self.backup = backup
        self.wipe = wipe
        self.confirm_message = confirm_message
        self.name_input = discord.ui.TextInput(
            label="Type the SOURCE server name to confirm",
            placeholder=backup["source_guild_name"],
            style=discord.TextStyle.short,
            max_length=100,
            required=True,
            row=0,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.name_input.value.strip() != self.backup["source_guild_name"]:
            return await interaction.response.send_message(
                "The name did not match. Wipe **cancelled** — no changes were made.", ephemeral=True
            )
        await interaction.response.edit_message(
            embed=self.cog.embed("Wipe + restore started", "Deleting existing structure, then restoring."),
            view=None,
        )
        await self.cog.run_load(self.ctx, self.backup, self.wipe, self.confirm_message)


class ConfirmDeleteView(discord.ui.View):
    """Confirmation for `backup delete` (irreversible)."""

    def __init__(self, cog: "Backup", ctx: Context, backup_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.backup_id = backup_id
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("You cannot confirm this action.", ephemeral=True)
        return False

    @discord.ui.button(label="Delete permanently", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._delete_backup(self.backup_id)
        await interaction.response.edit_message(
            embed=self.cog.embed("Backup deleted", f"`{self.backup_id}` was permanently removed."),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.cog.embed("Cancelled", "The backup was not deleted."), view=None
        )
        self.stop()


class Backup(CogMeta):
    """Back up and restore a server's structure (roles, channels, assets)."""

    def __init__(self, bot):
        super().__init__(bot)
        self.db: Optional[SqlitePool] = None
        # In-memory tracking of running jobs, keyed by job_id.
        # value: {"cancelled": bool, "rollback": bool, "objects": list, "current": int}
        self.active_jobs: dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle / schema
    # ------------------------------------------------------------------ #
    async def cog_load(self):
        path = "backups.db"
        db = await aiosqlite.connect(
            path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            # Autocommit mode so our manual transaction handling works like the main pool.
            isolation_level=None,
        )
        db.row_factory = aiosqlite.Row
        self.db = SqlitePool(db)
        for statement in (s.strip() for s in SCHEMA.split(";") if s.strip()):
            await self.db.execute(statement)
        logger.info("Backup cog loaded (backups.db)")

    async def cog_unload(self):
        if self.db is not None:
            try:
                await self.db.db.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def embed(self, title: str, description: Optional[str] = None, color: Optional[int] = None) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or COLORS.neutral,
        )
        embed.set_footer(text="Xrypton Backup")
        return embed

    async def gen_id(self) -> str:
        """Generate a unique 6-character uppercase A-Z backup ID."""
        for _ in range(10):
            candidate = "".join(random.choices(string.ascii_uppercase, k=6))
            exists = await self.db.fetchval("SELECT 1 FROM backups WHERE id = $1", candidate)
            if not exists:
                return candidate
        raise RuntimeError("Failed to generate a unique backup ID after 10 attempts.")

    def _bar(self, current: int, total: int) -> str:
        if total <= 0:
            return "[----------]"
        filled = min(10, int((current / total) * 10))
        return "[" + "#" * filled + "-" * (10 - filled) + f"] {current}/{total}"

    async def _set_progress(self, job_id: str, current: int, total: int, step: str, rollback_objects: Optional[list] = None):
        self.active_jobs.setdefault(job_id, {"cancelled": False, "rollback": False, "objects": []})
        self.active_jobs[job_id]["current"] = current
        await self.db.execute(
            "UPDATE backup_jobs SET progress_current = $1, progress_total = $2, current_step = $3, "
            "rollback_data = $4 WHERE job_id = $5",
            current, total, step,
            json.dumps(rollback_objects or self.active_jobs[job_id]["objects"]),
            job_id,
        )

    async def _edit_progress(self, message: discord.Message, current: int, total: int, step: str):
        try:
            await message.edit(embed=self.embed("Backup job running", f"```\n{self._bar(current, total)}\n```\n{step}"))
        except (discord.NotFound, discord.HTTPException):
            pass

    async def _tick(self, job_id, current, total, step, message, force=False):
        await self._set_progress(job_id, current, total, step)
        if force or current % 3 == 0:
            await self._edit_progress(message, current, total, step)

    def _is_cancelled(self, job_id: str) -> bool:
        job = self.active_jobs.get(job_id)
        return bool(job and job["cancelled"])

    # ------------------------------------------------------------------ #
    # Backup capture helpers
    # ------------------------------------------------------------------ #
    async def _store_overwrites(self, backup_id, kind, index, overwrites, role_id_to_index, guild):
        table = "backup_category_overwrites" if kind == "category" else "backup_channel_overwrites"
        key = "category_index" if kind == "category" else "channel_index"
        for target, ow in overwrites.items():
            # Member-target overwrites cannot be restored (members won't exist
            # on a new server), so they are intentionally skipped — see summary.
            if isinstance(target, discord.Member):
                continue
            if target == guild.default_role:
                t_everyone, t_idx = True, None
            elif isinstance(target, discord.Role):
                t_everyone, t_idx = False, role_id_to_index.get(target.id)
                if t_idx is None:
                    continue
            else:
                continue
            allow, deny = ow.pair()
            await self.db.execute(
                f"INSERT INTO {table} (backup_id, {key}, target_role_index, target_is_everyone, allow, deny) "
                f"VALUES ($1, $2, $3, $4, $5, $6)",
                backup_id, index, t_idx, t_everyone, allow.value, deny.value,
            )

    def _classify_channel(self, ch) -> Optional[str]:
        # In discord.py 2.7 announcement channels are TextChannel instances with
        # ChannelType.news, so classify by channel type rather than by class.
        t = getattr(ch, "type", None)
        if t == discord.ChannelType.text:
            return "text"
        if t == discord.ChannelType.voice:
            return "voice"
        if t == discord.ChannelType.news:
            return "announcement"
        if t == discord.ChannelType.stage_voice:
            return "stage"
        if t == discord.ChannelType.forum:
            return "forum"
        return None

    async def _gather_server_settings(self, guild: discord.Guild) -> dict:
        settings = {}
        try:
            settings["name"] = guild.name
        except Exception:
            pass
        for attr, serializer in (
            ("preferred_locale", lambda v: str(v)),
            ("verification_level", lambda v: v.value if v is not None else None),
            ("explicit_content_filter", lambda v: v.value if v is not None else None),
            ("default_notifications", lambda v: v.value if v is not None else None),
            ("afk_timeout", lambda v: v),
            ("premium_progress_bar_enabled", lambda v: int(bool(v))),
            ("system_channel_flags", lambda v: v.value if v is not None else None),
        ):
            try:
                value = getattr(guild, attr, None)
                if value is not None:
                    settings[attr] = serializer(value)
            except Exception:
                continue
        for attr in ("afk_channel_id", "system_channel_id", "rules_channel_id", "public_updates_channel_id"):
            try:
                value = getattr(guild, attr, None)
                settings[attr] = value.id if value else None
            except Exception:
                continue
        return settings

    # ------------------------------------------------------------------ #
    # Renderers (shared by `info` and `load` preview)
    # ------------------------------------------------------------------ #
    def _chunk_lines(self, lines: List[str], limit: int = 3500) -> List[str]:
        pages, current = [], ""
        for line in lines:
            if len(current) + len(line) + 1 > limit:
                pages.append(current)
                current = ""
            current += line + "\n"
        if current:
            pages.append(current)
        return pages

    def _chan_symbol(self, ch: dict) -> str:
        sym = CHANNEL_SYMBOLS.get(ch["type"], "#")
        return f"{sym} {ch['name']}"

    async def render_channel_tree(self, backup_id: str) -> List[str]:
        categories = await self.db.fetch(
            "SELECT * FROM backup_categories WHERE backup_id = $1 ORDER BY position ASC", backup_id
        )
        channels = await self.db.fetch(
            "SELECT * FROM backup_channels WHERE backup_id = $1 ORDER BY position ASC", backup_id
        )
        lines: List[str] = []
        for cat in categories:
            lines.append(f"˅ {cat['name']}")
            for ch in channels:
                if ch["category_index"] == cat["category_index"]:
                    lines.append("  " + self._chan_symbol(ch))
        uncat = [ch for ch in channels if ch["category_index"] is None]
        if uncat:
            lines.append("- Uncategorized")
            for ch in uncat:
                lines.append("  " + self._chan_symbol(ch))
        return self._chunk_lines(lines)

    async def render_role_list(self, backup_id: str) -> List[str]:
        roles = await self.db.fetch(
            "SELECT * FROM backup_roles WHERE backup_id = $1 ORDER BY position DESC", backup_id
        )
        lines: List[str] = []
        seen_managed = False
        for r in roles:
            if _b(r["is_managed"]) and not seen_managed:
                lines.append("---- Bot Roles ----")
                seen_managed = True
            tag = "managed" if _b(r["is_managed"]) else f"pos {r['position']}"
            lines.append(f"{r['name']}  ({tag})")
        return self._chunk_lines(lines)

    async def build_preview_embeds(self, backup_id: str, title: str = "Backup Preview") -> List[discord.Embed]:
        backup = await self.db.fetchrow("SELECT * FROM backups WHERE id = $1", backup_id)
        embeds: List[discord.Embed] = []
        header = self.embed(
            title,
            f"**Backup:** `{backup_id}` — {backup['source_guild_name']}\n"
            f"Roles: **{backup['role_count']}** | Channels: **{backup['channel_count']}** | "
            f"Assets: **{'yes' if _b(backup['includes_assets']) else 'no'}**",
        )
        embeds.append(header)
        tree_pages = await self.render_channel_tree(backup_id)
        for i, page in enumerate(tree_pages):
            e = self.embed(f"Channel Tree — {backup_id}")
            e.description = f"```\n{page}\n```"
            e.set_footer(text=f"Xrypton Backup | Tree {i + 1}/{len(tree_pages)}")
            embeds.append(e)
        role_pages = await self.render_role_list(backup_id)
        for i, page in enumerate(role_pages):
            e = self.embed(f"Roles — {backup_id}")
            e.description = f"```\n{page}\n```"
            e.set_footer(text=f"Xrypton Backup | Roles {i + 1}/{len(role_pages)}")
            embeds.append(e)
        return embeds

    # ------------------------------------------------------------------ #
    # CREATE
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(name="backup", aliases=["bk"], invoke_without_command=True,
                           description="Back up and restore a server's structure")
    async def backup(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(embed=self.embed(
                "Backup",
                "Create point-in-time snapshots of a server's **structure** (roles, channels, permission "
                "overwrites, and optional assets) and restore them later.\n\n"
                "`create [name]` — back up **this** server\n"
                "`load <id> [--wipe]` — restore a backup into **this** server\n"
                "`info <id>` — detailed view of one backup\n"
                "`list` — your backups\n"
                "`delete <id>` — permanently remove a backup\n"
                "`status [job]` — live progress of a running job\n"
                "`cancel <job> [--rollback]` — stop a running job\n\n"
                "**Out of scope for v1:** message history, member roles, ban list, and member-target "
                "permission overwrites (members won't exist on restore).",
            ))

    @backup.command(name="create", description="Back up the current server's structure")
    @commands.has_permissions(manage_guild=True)
    async def create(self, ctx: Context, *, name: Optional[str] = None):
        if not ctx.guild:
            return await ctx.warn("This command can only be used in a server.")

        prompt = AssetPromptView(self, ctx)
        prompt_msg = await ctx.send(
            embed=self.embed(
                "Create backup",
                "Include server **assets** (icon, splash, banner)? Assets make the backup larger and "
                "slower but let you restore the server's appearance.\n\n"
                "Default: **skip** (structure only).",
            ),
            view=prompt,
        )
        prompt.message = prompt_msg
        await prompt.wait()
        include_assets = prompt.include

        backup_id = await self.gen_id()
        guild = ctx.guild
        now = datetime.now(timezone.utc)
        label = name or f"{guild.name} {now.strftime('%Y-%m-%d %H:%M')}"

        job_id = "J" + uuid.uuid4().hex[:8].upper()
        self.active_jobs[job_id] = {"cancelled": False, "rollback": False, "objects": []}
        await self.db.execute(
            "INSERT INTO backup_jobs (job_id, backup_id, guild_id, user_id, job_type, status, "
            "progress_current, progress_total, current_step, started_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            job_id, backup_id, guild.id, ctx.author.id, "create", "running", 0, 0, "Starting...", now,
        )

        progress_msg = await ctx.send(embed=self.embed("Backup job running", "```\n[----------]\n```\nStarting..."))

        try:
            roles_sorted = sorted(guild.roles, key=lambda r: r.position)
            role_id_to_index = {role.id: idx for idx, role in enumerate(roles_sorted)}
            cats_sorted = sorted(guild.categories, key=lambda c: c.position)
            cat_id_to_index = {cat.id: cidx for cidx, cat in enumerate(cats_sorted)}
            chs = [c for c in guild.channels if not isinstance(c, discord.CategoryChannel)]
            chs_sorted = sorted(chs, key=lambda c: c.position)

            total = len(roles_sorted) + len(cats_sorted) + len(chs_sorted) + (4 if include_assets else 0)
            await self.db.execute(
                "UPDATE backup_jobs SET progress_total = $1 WHERE job_id = $2", total, job_id
            )

            await self.db.execute(
                "INSERT INTO backups (id, owner_id, source_guild_id, source_guild_name, name, created_at, "
                "includes_assets, channel_count, role_count, size_estimate_bytes) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                backup_id, ctx.author.id, guild.id, guild.name, label, now,
                include_assets, len(chs_sorted), len(roles_sorted), 0,
            )

            # Server settings (display-only in v1; not applied on restore).
            await self.db.execute(
                "INSERT INTO backup_settings (backup_id, key, value) VALUES ($1, $2, $3)",
                backup_id, "server", json.dumps(await self._gather_server_settings(guild)),
            )
            await self.db.execute(
                "INSERT INTO backup_settings (backup_id, key, value) VALUES ($1, $2, $3)",
                backup_id, "everyone_permissions", str(guild.default_role.permissions.value),
            )

            current = 0
            # Roles
            for idx, role in enumerate(roles_sorted):
                if self._is_cancelled(job_id):
                    break
                await self.db.execute(
                    "INSERT INTO backup_roles (backup_id, role_index, name, color, hoist, mentionable, "
                    "position, permissions, is_managed) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    backup_id, idx, role.name, role.color.value, role.hoist, role.mentionable,
                    role.position, role.permissions.value, role.managed,
                )
                current += 1
                await self._tick(job_id, current, total, f"Saving role: {role.name}", progress_msg)

            # Categories + their overwrites
            for cidx, cat in enumerate(cats_sorted):
                if self._is_cancelled(job_id):
                    break
                await self.db.execute(
                    "INSERT INTO backup_categories (backup_id, category_index, name, position) "
                    "VALUES ($1,$2,$3,$4)",
                    backup_id, cidx, cat.name, cat.position,
                )
                await self._store_overwrites(backup_id, "category", cidx, cat.overwrites, role_id_to_index, guild)
                current += 1
                await self._tick(job_id, current, total, f"Saving category: {cat.name}", progress_msg)

            # Channels + their overwrites
            for chidx, ch in enumerate(chs_sorted):
                if self._is_cancelled(job_id):
                    break
                ctype = self._classify_channel(ch)
                if not ctype:
                    continue
                cat_idx = cat_id_to_index.get(ch.category_id) if ch.category_id else None
                await self.db.execute(
                    "INSERT INTO backup_channels (backup_id, channel_index, category_index, type, name, "
                    "position, topic, nsfw, slowmode_delay, bitrate, user_limit) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    backup_id, chidx, cat_idx, ctype, ch.name, ch.position,
                    getattr(ch, "topic", None), getattr(ch, "nsfw", False),
                    getattr(ch, "slowmode_delay", 0) or 0, getattr(ch, "bitrate", None),
                    getattr(ch, "user_limit", None),
                )
                await self._store_overwrites(backup_id, "channel", chidx, ch.overwrites, role_id_to_index, guild)
                current += 1
                await self._tick(job_id, current, total, f"Saving channel: {ch.name}", progress_msg)

            # Assets
            size_estimate = (len(roles_sorted) + len(chs_sorted)) * 64
            if include_assets and not self._is_cancelled(job_id):
                for atype, asset in (
                    ("icon", guild.icon),
                    ("splash", guild.splash),
                    ("banner", guild.banner),
                    ("discovery_splash", guild.discovery_splash),
                ):
                    if not asset:
                        continue
                    try:
                        data = await asset.read()
                        await self.db.execute(
                            "INSERT INTO backup_assets (backup_id, asset_type, data) VALUES ($1,$2,$3)",
                            backup_id, atype, data,
                        )
                        size_estimate += len(data)
                    except Exception as error:
                        logger.warning("Failed to read asset {}: {}", atype, error)
                    current += 1
                    await self._tick(job_id, current, total, f"Saving asset: {atype}", progress_msg)

            await self.db.execute(
                "UPDATE backups SET size_estimate_bytes = $1 WHERE id = $2", size_estimate, backup_id
            )

            if self._is_cancelled(job_id):
                await self.db.execute("UPDATE backup_jobs SET status = 'cancelled' WHERE job_id = $1", job_id)
                # Rollback for create = remove the partial backup we just wrote.
                await self._delete_backup(backup_id)
                self.active_jobs.pop(job_id, None)
                return await ctx.send(embed=self.embed(
                    "Backup cancelled", f"Backup `{backup_id}` was discarded.", color=COLORS.warn
                ))

            await self.db.execute("UPDATE backup_jobs SET status = 'completed' WHERE job_id = $1", job_id)
            self.active_jobs.pop(job_id, None)
            return await ctx.send(embed=self.embed(
                "Backup created",
                f"Your backup is ready: **`{backup_id}`**\n\n"
                f"**Source:** {guild.name}\n"
                f"**Roles:** {len(roles_sorted)} | **Channels:** {len(chs_sorted)} | "
                f"**Assets:** {'yes' if include_assets else 'no'}\n"
                f"**Label:** {label}\n\n"
                f"Keep this ID safe — you need it to `load` or `delete` the backup. "
                f"Backups are tied to **you**, not the server, so you keep them even if you leave.",
                color=COLORS.approve,
            ))
        except Exception as error:
            logger.exception("Backup create failed: {}", error)
            await self.db.execute(
                "UPDATE backup_jobs SET status = 'failed', error_message = $1 WHERE job_id = $2",
                str(error), job_id,
            )
            self.active_jobs.pop(job_id, None)
            await self._edit_progress(progress_msg, 0, 0, f"Failed: {error}")
            return await ctx.send(embed=self.embed(
                "Backup failed", f"An error occurred:\n```\n{error}\n```", color=COLORS.deny
            ))

    # ------------------------------------------------------------------ #
    # LOAD
    # ------------------------------------------------------------------ #
    @backup.command(name="load", description="Restore a backup into the current server")
    @commands.has_permissions(manage_guild=True)
    async def load(self, ctx: Context, *, argument: str = ""):
        if not ctx.guild:
            return await ctx.warn("This command can only be used in a server.")
        parts = argument.split()
        if not parts:
            return await ctx.warn("Provide a backup ID: `,backup load <id> [--wipe]`")
        backup_id = parts[0].upper()
        wipe = "--wipe" in parts

        backup = await self.db.fetchrow("SELECT * FROM backups WHERE id = $1", backup_id)
        if not backup:
            return await ctx.warn(f"No backup found with ID `{backup_id}`.")
        if backup["owner_id"] != ctx.author.id:
            return await ctx.warn("You can only load backups that **you** created.")
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.warn("You need **Manage Server** in this server to load a backup.")
        if wipe and not ctx.author.guild_permissions.administrator:
            return await ctx.warn("`--wipe` requires **Administrator** because it deletes existing structure.")
        me = ctx.guild.me
        if not (me.guild_permissions.manage_channels and me.guild_permissions.manage_roles):
            return await ctx.warn("I need **Manage Channels** and **Manage Roles** in this server to restore.")

        embeds = await self.build_preview_embeds(backup_id, "Load Preview \u2014 confirm")
        await ctx.paginate(embeds)

        if wipe:
            deletable_channels = len([c for c in ctx.guild.channels if c != ctx.channel])
            deletable_roles = len([r for r in ctx.guild.roles if not r.is_default() and not r.managed])
            summary = (
                f"**Target server:** {ctx.guild.name} (`{ctx.guild.id}`)\n\n"
                f"This will **permanently delete** {deletable_channels} channels and {deletable_roles} roles "
                f"currently in this server, then restore the backup.\n\n"
                f"\u26a0\ufe0f **This cannot be undone.** The `@everyone` role, managed (bot) roles, and the "
                f"channel you ran this in will NOT be deleted. If cancelled partway through, deleted "
                f"channels/roles **cannot** be restored by rollback \u2014 only newly-created objects can."
            )
        else:
            summary = (
                f"**Target server:** {ctx.guild.name} (`{ctx.guild.id}`)\n\n"
                f"This will create **{backup['role_count']}** new roles and **{backup['channel_count']}** new "
                f"channels/categories in **this server**. Existing channels/roles will **not** be touched or "
                f"deleted."
            )

        view = ConfirmLoadView(self, ctx, backup, wipe)
        confirm_msg = await ctx.send(embed=self.embed("Confirm Load", summary), view=view)
        view.message = confirm_msg

    async def run_load(self, ctx: Context, backup: dict, wipe: bool, confirm_message: discord.Message):
        backup_id = backup["id"]
        guild = ctx.guild
        job_id = "J" + uuid.uuid4().hex[:8].upper()
        now = datetime.now(timezone.utc)
        self.active_jobs[job_id] = {"cancelled": False, "rollback": False, "objects": []}

        roles = await self.db.fetch("SELECT * FROM backup_roles WHERE backup_id = $1 ORDER BY position ASC", backup_id)
        categories = await self.db.fetch("SELECT * FROM backup_categories WHERE backup_id = $1 ORDER BY position ASC", backup_id)
        channels = await self.db.fetch("SELECT * FROM backup_channels WHERE backup_id = $1 ORDER BY position ASC", backup_id)
        assets = await self.db.fetch("SELECT * FROM backup_assets WHERE backup_id = $1", backup_id)

        total = len(roles) + len(categories) + len(channels) + (len(assets) if _b(backup["includes_assets"]) else 0)
        if wipe:
            total += len([c for c in guild.channels if c != ctx.channel]) + len(
                [r for r in guild.roles if not r.is_default() and not r.managed]
            )

        await self.db.execute(
            "INSERT INTO backup_jobs (job_id, backup_id, guild_id, user_id, job_type, status, "
            "progress_current, progress_total, current_step, started_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            job_id, backup_id, guild.id, ctx.author.id, "load", "running", 0, total, "Starting...", now,
        )
        progress_msg = await ctx.send(embed=self.embed("Restore running", "```\n[----------]\n```\nStarting..."))

        created_objects: List[dict] = []
        failures: List[str] = []
        current = 0

        def record(obj):
            created_objects.append(obj)
            self.active_jobs[job_id]["objects"].append(obj)

        async def maybe_cancel():
            if self._is_cancelled(job_id):
                await self._finish_load(
                    ctx, job_id, backup_id, progress_msg, created_objects, failures, cancelled=True, wipe=wipe
                )
                return True
            return False

        try:
            # ---- WIPE phase ----
            if wipe:
                for ch in list(guild.channels):
                    if ch == ctx.channel:
                        continue
                    try:
                        await ch.delete(reason="Backup --wipe restore")
                        record({"type": "channel", "id": ch.id})
                    except Exception as error:
                        failures.append(f"delete channel {ch.name}: {error}")
                    current += 1
                    await self._tick(job_id, current, total, f"Deleting channel: {ch.name}", progress_msg)
                    if await maybe_cancel():
                        return

                for role in list(guild.roles):
                    if role.is_default() or role.managed:
                        continue
                    try:
                        await role.delete(reason="Backup --wipe restore")
                        record({"type": "role", "id": role.id})
                    except Exception as error:
                        failures.append(f"delete role {role.name}: {error}")
                    current += 1
                    await self._tick(job_id, current, total, f"Deleting role: {role.name}", progress_msg)
                    if await maybe_cancel():
                        return

                ep = await self.db.fetchval(
                    "SELECT value FROM backup_settings WHERE backup_id = $1 AND key = 'everyone_permissions'",
                    backup_id,
                )
                if ep is not None:
                    try:
                        await guild.default_role.edit(permissions=discord.Permissions(int(ep)))
                    except Exception as error:
                        failures.append(f"edit @everyone permissions: {error}")

            # ---- ROLES ----
            role_map: dict[int, discord.Role] = {}
            pos_map: dict[int, int] = {}
            for r in roles:
                if _b(r["is_managed"]) or r["name"] == "@everyone":
                    continue
                try:
                    new_role = await guild.create_role(
                        name=r["name"],
                        colour=discord.Color(r["color"] or 0),
                        hoist=_b(r["hoist"]),
                        mentionable=_b(r["mentionable"]),
                        permissions=discord.Permissions(r["permissions"]),
                        reason="Backup restore",
                    )
                    role_map[r["role_index"]] = new_role
                    pos_map[r["role_index"]] = r["position"]
                    record({"type": "role", "id": new_role.id})
                except Exception as error:
                    failures.append(f"create role {r['name']}: {error}")
                current += 1
                await self._tick(job_id, current, total, f"Creating role: {r['name']}", progress_msg)
                if await maybe_cancel():
                    return

            # Apply role positions. Discord forbids moving a role above the bot's
            # own top role (even with Administrator), so only reorder positions that
            # sit strictly below the bot's highest role — the rest keep their natural
            # (correct relative) stacking from the descending create order.
            if role_map:
                try:
                    bot_top = max((role.position for role in guild.me.roles), default=0)
                    order_map = {
                        role_map[idx]: pos
                        for idx, pos in pos_map.items()
                        if pos < bot_top
                    }
                    if order_map:
                        await guild.edit_role_positions(order_map)
                except Exception as error:
                    failures.append(f"reorder roles: {error}")

            # ---- CATEGORIES ----
            cat_map: dict[int, discord.CategoryChannel] = {}
            for c in categories:
                overwrites = await self._build_overwrites(backup_id, "category", c["category_index"], role_map, guild)
                try:
                    new_cat = await guild.create_category(
                        name=c["name"], position=c["position"], overwrites=overwrites, reason="Backup restore"
                    )
                    cat_map[c["category_index"]] = new_cat
                    record({"type": "category", "id": new_cat.id})
                except Exception as error:
                    failures.append(f"create category {c['name']}: {error}")
                current += 1
                await self._tick(job_id, current, total, f"Creating category: {c['name']}", progress_msg)
                if await maybe_cancel():
                    return

            # ---- CHANNELS ----
            for ch in channels:
                overwrites = await self._build_overwrites(backup_id, "channel", ch["channel_index"], role_map, guild)
                parent = cat_map.get(ch["category_index"])
                base = dict(
                    name=ch["name"], position=ch["position"], overwrites=overwrites,
                    category=parent, reason="Backup restore",
                )
                ctype = ch["type"]
                try:
                    if ctype == "text":
                        new = await guild.create_text_channel(
                            topic=ch["topic"], nsfw=_b(ch["nsfw"]),
                            slowmode_delay=ch["slowmode_delay"] or 0, **base,
                        )
                    elif ctype == "announcement":
                        # Discord only allows announcement (news) channels on Community
                        # servers; outside one the API rejects type 5. Fall back to a
                        # normal text channel so the restore still succeeds.
                        try:
                            new = await guild.create_text_channel(
                                news=True, topic=ch["topic"], nsfw=_b(ch["nsfw"]), **base,
                            )
                        except discord.HTTPException:
                            new = await guild.create_text_channel(
                                topic=ch["topic"], nsfw=_b(ch["nsfw"]), **base,
                            )
                            failures.append(
                                f"channel {ch['name']}: restored as text (announcements require a Community server)"
                            )
                    elif ctype == "voice":
                        new = await guild.create_voice_channel(
                            bitrate=ch["bitrate"] or 64000, user_limit=ch["user_limit"] or 0, **base,
                        )
                    elif ctype == "stage":
                        new = await guild.create_stage_channel(**base)
                    elif ctype == "forum":
                        new = await guild.create_forum(nsfw=_b(ch["nsfw"]), **base)
                    else:
                        continue
                    record({"type": "channel", "id": new.id})
                except Exception as error:
                    failures.append(f"create channel {ch['name']}: {error}")
                current += 1
                await self._tick(job_id, current, total, f"Creating channel: {ch['name']}", progress_msg)
                if await maybe_cancel():
                    return

            # ---- ASSETS ----
            if _b(backup["includes_assets"]):
                for a in assets:
                    atype = a["asset_type"]
                    data = a["data"]
                    try:
                        if atype == "icon":
                            await guild.edit(icon=data)
                        elif atype == "splash":
                            await guild.edit(splash=data)
                        elif atype == "banner":
                            await guild.edit(banner=data)
                        elif atype == "discovery_splash":
                            await guild.edit(discovery_splash=data)
                    except discord.HTTPException as error:
                        failures.append(f"restore {atype}: {error}")
                    current += 1
                    await self._tick(job_id, current, total, f"Restoring asset: {atype}", progress_msg)
                    if await maybe_cancel():
                        return

            await self._finish_load(
                ctx, job_id, backup_id, progress_msg, created_objects, failures, cancelled=False, wipe=wipe
            )
        except Exception as error:
            logger.exception("Backup load failed: {}", error)
            await self.db.execute(
                "UPDATE backup_jobs SET status = 'failed', error_message = $1 WHERE job_id = $2",
                str(error), job_id,
            )
            self.active_jobs.pop(job_id, None)
            await self._edit_progress(progress_msg, current, total, f"Failed: {error}")
            await ctx.send(embed=self.embed(
                "Restore failed", f"An error occurred:\n```\n{error}\n```", color=COLORS.deny
            ))

    async def _build_overwrites(self, backup_id, kind, index, role_map, guild) -> dict:
        table = "backup_category_overwrites" if kind == "category" else "backup_channel_overwrites"
        key = "category_index" if kind == "category" else "channel_index"
        rows = await self.db.fetch(
            f"SELECT * FROM {table} WHERE backup_id = $1 AND {key} = $2", backup_id, index
        )
        overwrites = {}
        for ow in rows:
            if _b(ow["target_is_everyone"]):
                target = guild.default_role
            else:
                target = role_map.get(ow["target_role_index"])
                if target is None:
                    continue
            overwrites[target] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(ow["allow"]), discord.Permissions(ow["deny"])
            )
        return overwrites

    async def _finish_load(self, ctx, job_id, backup_id, progress_msg, created_objects, failures, cancelled, wipe):
        if cancelled:
            # Rollback only the objects we created during this job.
            rollback = self.active_jobs.get(job_id, {}).get("rollback", False)
            if rollback:
                for obj in reversed(created_objects):
                    try:
                        if obj["type"] in ("channel", "category"):
                            target = ctx.guild.get_channel(obj["id"])
                            if target:
                                await target.delete(reason="Backup load rollback")
                        elif obj["type"] == "role":
                            target = ctx.guild.get_role(obj["id"])
                            if target and not target.is_default() and not target.managed:
                                await target.delete(reason="Backup load rollback")
                    except Exception as error:
                        failures.append(f"rollback {obj['type']} {obj['id']}: {error}")
                status = "cancelled (rolled back)"
            else:
                status = "cancelled"
            await self.db.execute(
                "UPDATE backup_jobs SET status = 'cancelled', rollback_data = $1 WHERE job_id = $2",
                json.dumps(created_objects), job_id,
            )
            self.active_jobs.pop(job_id, None)
            await self._edit_progress(progress_msg, 0, 0, status)
            return await ctx.send(embed=self.embed(
                "Load cancelled",
                "The job was cancelled. " + (
                    "All newly-created objects were rolled back." if rollback
                    else "Objects already created were left in place."
                ),
                color=COLORS.warn,
            ))

        await self.db.execute(
            "UPDATE backup_jobs SET status = 'completed', rollback_data = $1 WHERE job_id = $2",
            json.dumps(created_objects), job_id,
        )
        self.active_jobs.pop(job_id, None)
        created_count = len(created_objects)
        summary = (
            f"Restore **completed** into {ctx.guild.name}.\n\n"
            f"Objects created: **{created_count}**"
            + (f" (after wiping existing structure)" if wipe else "")
            + "\n"
        )
        if failures:
            summary += f"\n**{len(failures)} issue(s):**\n" + "\n".join(f"- {f}" for f in failures[:15])
            if len(failures) > 15:
                summary += f"\n- ...and {len(failures) - 15} more"
        else:
            summary += "\nAll objects restored without errors."
        if not wipe:
            summary += "\n\nNote: roles above the bot's highest role were placed as high as possible."
        await self._edit_progress(progress_msg, 0, 0, "Completed")
        return await ctx.send(embed=self.embed("Restore complete", summary, color=COLORS.approve))

    # ------------------------------------------------------------------ #
    # INFO / LIST
    # ------------------------------------------------------------------ #
    @backup.command(name="info", description="Show details about a backup (or list your backups)")
    async def info(self, ctx: Context, backup_id: Optional[str] = None):
        if backup_id is None:
            return await self._list_backups(ctx)
        backup_id = backup_id.upper()
        backup = await self.db.fetchrow("SELECT * FROM backups WHERE id = $1", backup_id)
        if not backup:
            return await ctx.warn(f"No backup found with ID `{backup_id}`.")
        if backup["owner_id"] != ctx.author.id:
            return await ctx.warn("You can only view backups that **you** created.")

        embeds = await self.build_preview_embeds(backup_id, f"Backup Info \u2014 {backup_id}")
        info = self.embed(
            f"Backup `{backup_id}`",
            f"**Label:** {backup['name'] or backup['source_guild_name']}\n"
            f"**Source server:** {backup['source_guild_name']} (`{backup['source_guild_id']}`)\n"
            f"**Owner:** <@{backup['owner_id']}>\n"
            f"**Created:** <t:{int(backup['created_at'].timestamp())}:f>\n"
            f"**Roles:** {backup['role_count']} | **Channels:** {backup['channel_count']}\n"
            f"**Assets included:** {'yes' if _b(backup['includes_assets']) else 'no'}\n"
            f"**Size estimate:** {self.bot.format_size(backup['size_estimate_bytes'] or 0)}",
        )
        embeds.insert(0, info)
        await ctx.paginate(embeds)

    async def _list_backups(self, ctx: Context):
        rows = await self.db.fetch(
            "SELECT * FROM backups WHERE owner_id = $1 ORDER BY created_at DESC", ctx.author.id
        )
        if not rows:
            return await ctx.warn("You don't have any backups yet. Use `,backup create`.")
        embeds = []
        for offset in range(0, len(rows), 6):
            chunk = rows[offset:offset + 6]
            desc = ""
            for b in chunk:
                desc += (
                    f"`{b['id']}` \u2014 **{b['name'] or b['source_guild_name']}**\n"
                    f"> Source: {b['source_guild_name']} | {b['role_count']} roles, "
                    f"{b['channel_count']} channels | <t:{int(b['created_at'].timestamp())}:f>\n"
                )
            e = self.embed("Your Backups", desc)
            e.set_footer(text=f"Xrypton Backup | Page {len(embeds) + 1}/{(len(rows) + 5) // 6}")
            embeds.append(e)
        await ctx.paginate(embeds)

    @backup.command(name="list", description="List all of your backups")
    async def list_backups(self, ctx: Context):
        await self._list_backups(ctx)

    # ------------------------------------------------------------------ #
    # DELETE
    # ------------------------------------------------------------------ #
    @backup.command(name="delete", description="Permanently delete one of your backups")
    async def delete(self, ctx: Context, backup_id: str):
        backup_id = backup_id.upper()
        backup = await self.db.fetchrow("SELECT * FROM backups WHERE id = $1", backup_id)
        if not backup:
            return await ctx.warn(f"No backup found with ID `{backup_id}`.")
        if backup["owner_id"] != ctx.author.id:
            return await ctx.warn("You can only delete backups that **you** created.")
        view = ConfirmDeleteView(self, ctx, backup_id)
        msg = await ctx.send(
            embed=self.embed(
                "Delete backup?",
                f"This will **permanently** delete backup `{backup_id}` "
                f"({backup['source_guild_name']}) and all of its data. **This cannot be undone.**",
                color=COLORS.warn,
            ),
            view=view,
        )
        view.message = msg

    async def _delete_backup(self, backup_id: str):
        await self.db.execute("DELETE FROM backups WHERE id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_settings WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_roles WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_categories WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_category_overwrites WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_channels WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_channel_overwrites WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_assets WHERE backup_id = $1", backup_id)
        await self.db.execute("DELETE FROM backup_jobs WHERE backup_id = $1", backup_id)

    # ------------------------------------------------------------------ #
    # STATUS / CANCEL
    # ------------------------------------------------------------------ #
    def _job_embed(self, job: dict) -> discord.Embed:
        started = job["started_at"]
        elapsed = ""
        if started:
            try:
                elapsed = f" | elapsed <t:{int(started.timestamp())}:R>"
            except Exception:
                pass
        return self.embed(
            f"Job `{job['job_id']}` \u2014 {job['status']}",
            f"**Type:** {job['job_type']}\n"
            f"**Backup:** {job['backup_id']}\n"
            f"**Step:** {job['current_step']}\n"
            f"```\n{self._bar(job['progress_current'] or 0, job['progress_total'] or 0)}\n```{elapsed}",
        )

    @backup.command(name="status", description="Show the status of a running backup job")
    async def status(self, ctx: Context, job_id: Optional[str] = None):
        if job_id:
            job = await self.db.fetchrow(
                "SELECT * FROM backup_jobs WHERE job_id = $1 AND user_id = $2", job_id.upper(), ctx.author.id
            )
            if not job:
                return await ctx.warn(f"No job found with ID `{job_id}`.")
            return await ctx.send(embed=self._job_embed(job))
        jobs = await self.db.fetch(
            "SELECT * FROM backup_jobs WHERE user_id = $1 AND status = 'running' ORDER BY started_at DESC",
            ctx.author.id,
        )
        if not jobs:
            return await ctx.warn("You have no running backup jobs.")
        embeds = [self._job_embed(j) for j in jobs]
        await ctx.paginate(embeds)

    @backup.command(name="cancel", description="Cancel a running backup job")
    async def cancel(self, ctx: Context, *, argument: str = ""):
        parts = argument.split()
        if not parts:
            return await ctx.warn("Provide a job ID or backup ID: `,backup cancel <id> [--rollback]`")
        token = parts[0].upper()
        rollback = "--rollback" in parts

        job = None
        if token.startswith("J"):
            job = await self.db.fetchrow(
                "SELECT * FROM backup_jobs WHERE job_id = $1 AND user_id = $2", token, ctx.author.id
            )
        if not job:
            job = await self.db.fetchrow(
                "SELECT * FROM backup_jobs WHERE backup_id = $1 AND user_id = $2 AND status = 'running' "
                "ORDER BY started_at DESC LIMIT 1", token, ctx.author.id
            )
        if not job:
            return await ctx.warn("No running job found for that ID.")

        job_id = job["job_id"]
        aj = self.active_jobs.get(job_id)
        if aj:
            aj["cancelled"] = True
            aj["rollback"] = rollback
        await self.db.execute("UPDATE backup_jobs SET status = 'cancelled' WHERE job_id = $1", job_id)

        if rollback:
            await ctx.approve(
                f"Cancellation requested for job `{job_id}` with **rollback**. Newly-created objects will be "
                f"reverted (existing/deleted ones cannot be un-deleted)."
            )
        else:
            await ctx.approve(
                f"Cancellation requested for job `{job_id}`. Already-created objects will remain in place."
            )


async def setup(bot):
    await bot.add_cog(Backup(bot))
