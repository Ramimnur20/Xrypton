from __future__ import annotations

import asyncio
import io
import json
import os
import pathlib
import random
import string
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import aiosqlite
import discord
from discord import (
    ButtonStyle,
    CategoryChannel,
    Colour,
    Embed,
    ForumChannel,
    Guild,
    HTTPException,
    Member,
    Message,
    NotFound,
    PermissionOverwrite,
    Permissions,
    RateLimited,
    Role,
    StageChannel,
    TextChannel,
    TextStyle,
    VoiceChannel,
    ui,
)
from discord.ext import commands
from discord.ext.commands import hybrid_group
from loguru import logger

from base.config import COLORS, EMOJIS
from base.context import Context
from base.managers.predicates import example, has_permissions
from base.managers.types import CogMeta
from base.Xrypton import SqlitePool


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS backups (
        id TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        source_guild_id INTEGER NOT NULL,
        source_guild_name TEXT NOT NULL,
        name TEXT,
        created_at TIMESTAMP NOT NULL,
        includes_assets INTEGER NOT NULL DEFAULT 0,
        channel_count INTEGER DEFAULT 0,
        role_count INTEGER DEFAULT 0,
        category_count INTEGER DEFAULT 0,
        size_estimate_bytes INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_settings (
        backup_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (backup_id, key),
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_roles (
        backup_id TEXT NOT NULL,
        role_index INTEGER NOT NULL,
        name TEXT NOT NULL,
        color INTEGER DEFAULT 0,
        hoist INTEGER DEFAULT 0,
        mentionable INTEGER DEFAULT 0,
        position INTEGER DEFAULT 0,
        permissions BIGINT DEFAULT 0,
        is_managed INTEGER DEFAULT 0,
        PRIMARY KEY (backup_id, role_index),
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_categories (
        backup_id TEXT NOT NULL,
        category_index INTEGER NOT NULL,
        name TEXT NOT NULL,
        position INTEGER DEFAULT 0,
        PRIMARY KEY (backup_id, category_index),
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_category_overwrites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_id TEXT NOT NULL,
        category_index INTEGER NOT NULL,
        target_role_index INTEGER,
        target_is_everyone INTEGER DEFAULT 0,
        allow BIGINT DEFAULT 0,
        deny BIGINT DEFAULT 0,
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_channels (
        backup_id TEXT NOT NULL,
        channel_index INTEGER NOT NULL,
        category_index INTEGER,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        position INTEGER DEFAULT 0,
        topic TEXT,
        nsfw INTEGER DEFAULT 0,
        slowmode_delay INTEGER DEFAULT 0,
        bitrate INTEGER,
        user_limit INTEGER,
        PRIMARY KEY (backup_id, channel_index),
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_channel_overwrites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_id TEXT NOT NULL,
        channel_index INTEGER NOT NULL,
        target_role_index INTEGER,
        target_is_everyone INTEGER DEFAULT 0,
        allow BIGINT DEFAULT 0,
        deny BIGINT DEFAULT 0,
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_assets (
        backup_id TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        data BLOB NOT NULL,
        PRIMARY KEY (backup_id, asset_type),
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_emojis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_id TEXT NOT NULL,
        name TEXT NOT NULL,
        data BLOB NOT NULL,
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_stickers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        emoji TEXT,
        data BLOB NOT NULL,
        FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_jobs (
        job_id TEXT PRIMARY KEY,
        backup_id TEXT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL,
        progress_current INTEGER DEFAULT 0,
        progress_total INTEGER DEFAULT 0,
        current_step TEXT,
        started_at TIMESTAMP NOT NULL,
        rollback_data TEXT,
        error_message TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_backups_owner ON backups(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_backup_jobs_user ON backup_jobs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_backup_jobs_guild ON backup_jobs(guild_id)",
    "CREATE INDEX IF NOT EXISTS idx_backup_roles_bid ON backup_roles(backup_id)",
    "CREATE INDEX IF NOT EXISTS idx_backup_channels_bid ON backup_channels(backup_id)",
)


def generate_backup_id(length: int = 6) -> str:
    """Generate a random 6-character uppercase A-Z backup identifier."""
    return "".join(random.choices(string.ascii_uppercase, k=length))


def generate_job_id() -> str:
    """Generate an 8-character unique job identifier."""
    return "J" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))


def format_progress_bar(current: int, total: int, length: int = 14) -> str:
    """Render a visual ASCII progress bar."""
    if total <= 0:
        return f"[{'░' * length}] 0% (0/0)"
    ratio = min(1.0, max(0.0, current / total))
    filled = int(round(length * ratio))
    bar = "█" * filled + "░" * (length - filled)
    return f"`[{bar}]` **{int(ratio * 100)}%** ({current}/{total})"


def render_channel_tree_chunks(
    channels: List[Dict[str, Any]],
    categories: List[Dict[str, Any]],
    max_chunk_chars: int = 1750,
) -> List[str]:
    """
    Render a clean monospace channel tree matching the spec, chunked for embeds.
    """
    cat_map: Dict[int, str] = {
        cat["category_index"]: cat["name"] for cat in categories
    }
    grouped: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for cat in categories:
        grouped[cat["category_index"]] = []
    grouped[None] = []

    for chan in sorted(channels, key=lambda c: c.get("position", 0)):
        cat_idx = chan.get("category_index")
        if cat_idx not in grouped:
            grouped[None].append(chan)
        else:
            grouped[cat_idx].append(chan)

    def get_symbol(c_type: str) -> str:
        t = (c_type or "text").lower()
        if t == "announcement":
            return "!"
        elif t == "voice":
            return "🔊"
        elif t == "forum":
            return "💬"
        elif t == "stage":
            return "🎤"
        return "#"

    lines: List[str] = []

    # 1. Uncategorized channels at top if any exist
    if grouped[None]:
        lines.append("- Uncategorized")
        for ch in grouped[None]:
            sym = get_symbol(ch.get("type", "text"))
            lines.append(f"    {sym} {ch.get('name', 'unnamed')}")

    # 2. Categorized channels in category position order
    sorted_cats = sorted(categories, key=lambda c: c.get("position", 0))
    for cat in sorted_cats:
        c_idx = cat["category_index"]
        c_name = cat.get("name", "Category")
        lines.append(f"˅ {c_name}")
        chans_in_cat = grouped.get(c_idx, [])
        if not chans_in_cat:
            lines.append("    (empty category)")
        else:
            for ch in chans_in_cat:
                sym = get_symbol(ch.get("type", "text"))
                lines.append(f"    {sym} {ch.get('name', 'unnamed')}")

    if not lines:
        return ["```\n(No channels in backup)\n```"]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chunk_chars and current_chunk:
            chunks.append("```\n" + "\n".join(current_chunk) + "\n```")
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("```\n" + "\n".join(current_chunk) + "\n```")

    return chunks


def render_role_list_chunks(
    roles: List[Dict[str, Any]],
    max_chunk_chars: int = 1750,
) -> List[str]:
    """
    Render a clean monospace role hierarchy list, chunked for embeds.
    """
    if not roles:
        return ["```\n(No roles in backup)\n```"]

    sorted_roles = sorted(roles, key=lambda r: r.get("position", 0), reverse=True)
    user_roles = [r for r in sorted_roles if not r.get("is_managed")]
    bot_roles = [r for r in sorted_roles if r.get("is_managed")]

    lines: List[str] = []

    if user_roles:
        lines.append("---- Hierarchy (Top to Bottom) ----")
        for r in user_roles:
            name = r.get("name", "Role")
            hoist = " [H]" if r.get("hoist") else ""
            color_val = r.get("color", 0)
            color_hex = f"#{color_val:06x}" if color_val else "#default"
            lines.append(f"  • {name}{hoist} ({color_hex})")

    if bot_roles:
        if lines:
            lines.append("")
        lines.append("---- Bot / Integration Roles ----")
        for r in bot_roles:
            name = r.get("name", "Bot Role")
            lines.append(f"  • [BOT] {name}")

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chunk_chars and current_chunk:
            chunks.append("```\n" + "\n".join(current_chunk) + "\n```")
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("```\n" + "\n".join(current_chunk) + "\n```")

    return chunks


class AssetPromptView(ui.View):
    """Interactive prompt asking whether to include assets in the backup."""

    def __init__(self, ctx: Context):
        super().__init__(timeout=60.0)
        self.ctx = ctx
        self.include_assets: Optional[bool] = None
        self.cancelled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "You are not authorized to interact with this prompt.", ephemeral=True
            )
            return False
        return True

    @ui.button(
        label="Include Assets (Icons/Emojis)",
        style=ButtonStyle.primary,
        emoji="🖼️",
    )
    async def with_assets(self, interaction: discord.Interaction, button: ui.Button):
        self.include_assets = True
        self.stop()
        await interaction.response.defer()

    @ui.button(
        label="Structure Only (Fast)",
        style=ButtonStyle.secondary,
        emoji="⚡",
    )
    async def structure_only(
        self, interaction: discord.Interaction, button: ui.Button
    ):
        self.include_assets = False
        self.stop()
        await interaction.response.defer()

    @ui.button(label="Cancel", style=ButtonStyle.danger, emoji="❌")
    async def cancel_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.cancelled = True
        self.stop()
        await interaction.response.defer()


class LoadConfirmView(ui.View):
    """Standard additive load confirmation view."""

    def __init__(self, ctx: Context):
        super().__init__(timeout=90.0)
        self.ctx = ctx
        self.confirmed: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "You cannot confirm this action.", ephemeral=True
            )
            return False
        return True

    @ui.button(label="Confirm Load", style=ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @ui.button(label="Cancel", style=ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class WipeConfirmModal(ui.Modal, title="Confirm Server Wipe & Restore"):
    """Step 2 modal text verification for --wipe mode."""

    def __init__(self, target_guild_name: str, backup_id: str):
        super().__init__()
        self.target_guild_name = target_guild_name
        self.backup_id = backup_id
        self.confirmed = False

        self.verification_input = ui.TextInput(
            label=f"Type '{target_guild_name}' or '{backup_id}'",
            placeholder=f"Enter server name or {backup_id} to confirm wipe",
            style=TextStyle.short,
            min_length=1,
            max_length=100,
            required=True,
        )
        self.add_item(self.verification_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_val = self.verification_input.value.strip().lower()
        if (
            user_val == self.target_guild_name.lower()
            or user_val == self.backup_id.lower()
        ):
            self.confirmed = True
            await interaction.response.defer()
        else:
            self.confirmed = False
            await interaction.response.send_message(
                f"{EMOJIS.WARN} Verification failed. Server name or backup ID did not match.",
                ephemeral=True,
            )


class WipeConfirmView(ui.View):
    """Step 1 confirmation view for --wipe mode triggering the verification modal."""

    def __init__(self, ctx: Context, backup_id: str):
        super().__init__(timeout=120.0)
        self.ctx = ctx
        self.backup_id = backup_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "You cannot confirm this destructive action.", ephemeral=True
            )
            return False
        return True

    @ui.button(
        label="Proceed to Verification", style=ButtonStyle.danger, emoji="⚠️"
    )
    async def proceed(self, interaction: discord.Interaction, button: ui.Button):
        modal = WipeConfirmModal(self.ctx.guild.name, self.backup_id)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.confirmed:
            self.confirmed = True
            self.stop()

    @ui.button(label="Cancel", style=ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class DeleteConfirmView(ui.View):
    """Confirmation view for permanently deleting a backup."""

    def __init__(self, ctx: Context, backup_id: str):
        super().__init__(timeout=60.0)
        self.ctx = ctx
        self.backup_id = backup_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "You cannot confirm this action.", ephemeral=True
            )
            return False
        return True

    @ui.button(label="Delete Permanently", style=ButtonStyle.danger, emoji="🗑️")
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @ui.button(label="Cancel", style=ButtonStyle.secondary, emoji="❌")
    async def cancel_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class Backup(CogMeta):
    """Create, restore, inspect, and manage complete server backups."""

    def __init__(self, bot):
        super().__init__(bot)
        self.db_conn: Optional[aiosqlite.Connection] = None
        self.db: Optional[SqlitePool] = None
        self.cancel_requested: Set[str] = set()
        self.active_tasks: Dict[str, asyncio.Task] = {}

    async def cog_load(self):
        db_path = pathlib.Path("backups.db")
        self.db_conn = await aiosqlite.connect(
            str(db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )
        self.db_conn.row_factory = aiosqlite.Row
        self.db = SqlitePool(self.db_conn)
        await self.ensure_schema()
        logger.info("Backup cog database connection established at backups.db")

    async def cog_unload(self):
        for task in self.active_tasks.values():
            if not task.done():
                task.cancel()
        if self.db_conn:
            await self.db_conn.close()
        logger.info("Backup cog unloaded and backups.db connection closed.")

    async def ensure_schema(self):
        for stmt in SCHEMA_STATEMENTS:
            await self.db.execute(stmt)

    def embed(
        self,
        title: str,
        description: str,
        color: Optional[discord.Color] = None,
    ) -> discord.Embed:
        e = discord.Embed(
            title=title,
            description=description,
            color=color if color is not None else COLORS.neutral,
            timestamp=datetime.now(timezone.utc),
        )
        e.set_footer(text="Xrypton Backups")
        return e

    async def get_unique_backup_id(self) -> str:
        for _ in range(10):
            candidate = generate_backup_id()
            exists = await self.db.fetchval(
                "SELECT 1 FROM backups WHERE id = $1", candidate
            )
            if not exists:
                return candidate
        raise RuntimeError("Failed to generate a unique backup ID after 10 attempts.")

    async def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.fetchrow(
            "SELECT * FROM backups WHERE id = $1", backup_id.upper()
        )

    async def get_backup_roles(self, backup_id: str) -> List[Dict[str, Any]]:
        return await self.db.fetch(
            "SELECT * FROM backup_roles WHERE backup_id = $1 ORDER BY position ASC",
            backup_id.upper(),
        )

    async def get_backup_categories(self, backup_id: str) -> List[Dict[str, Any]]:
        return await self.db.fetch(
            "SELECT * FROM backup_categories WHERE backup_id = $1 ORDER BY position ASC",
            backup_id.upper(),
        )

    async def get_backup_channels(self, backup_id: str) -> List[Dict[str, Any]]:
        return await self.db.fetch(
            "SELECT * FROM backup_channels WHERE backup_id = $1 ORDER BY position ASC",
            backup_id.upper(),
        )

    async def get_backup_settings(self, backup_id: str) -> Dict[str, str]:
        rows = await self.db.fetch(
            "SELECT key, value FROM backup_settings WHERE backup_id = $1",
            backup_id.upper(),
        )
        return {r["key"]: r["value"] for r in rows}

    async def delete_backup_data(self, backup_id: str) -> None:
        bid = backup_id.upper()
        tables = (
            "backup_category_overwrites",
            "backup_channel_overwrites",
            "backup_channels",
            "backup_categories",
            "backup_roles",
            "backup_settings",
            "backup_assets",
            "backup_emojis",
            "backup_stickers",
            "backup_jobs",
            "backups",
        )
        for t in tables:
            try:
                await self.db.execute(f"DELETE FROM {t} WHERE backup_id = $1", bid)
            except Exception:
                pass
        try:
            await self.db.execute("DELETE FROM backups WHERE id = $1", bid)
        except Exception:
            pass

    async def create_job(
        self,
        job_id: str,
        backup_id: Optional[str],
        guild_id: int,
        user_id: int,
        job_type: str,
        progress_total: int,
        initial_step: str = "Initializing...",
    ):
        await self.db.execute(
            """
            INSERT INTO backup_jobs (
                job_id, backup_id, guild_id, user_id, job_type, status,
                progress_current, progress_total, current_step, started_at, rollback_data
            ) VALUES ($1, $2, $3, $4, $5, 'running', 0, $6, $7, $8, '[]')
            """,
            job_id,
            backup_id,
            guild_id,
            user_id,
            job_type,
            progress_total,
            initial_step,
            datetime.now(timezone.utc),
        )

    async def update_job(
        self,
        job_id: str,
        progress_current: int,
        current_step: str,
        rollback_entry: Optional[Dict[str, Any]] = None,
    ):
        if rollback_entry:
            row = await self.db.fetchrow(
                "SELECT rollback_data FROM backup_jobs WHERE job_id = $1", job_id
            )
            raw = row["rollback_data"] if row and row.get("rollback_data") else "[]"
            try:
                items = json.loads(raw)
            except Exception:
                items = []
            items.append(rollback_entry)
            await self.db.execute(
                """
                UPDATE backup_jobs
                SET progress_current = $1, current_step = $2, rollback_data = $3
                WHERE job_id = $4
                """,
                progress_current,
                current_step,
                json.dumps(items),
                job_id,
            )
        else:
            await self.db.execute(
                """
                UPDATE backup_jobs
                SET progress_current = $1, current_step = $2
                WHERE job_id = $3
                """,
                progress_current,
                current_step,
                job_id,
            )

    async def is_job_cancelled(self, job_id: str) -> bool:
        if job_id in self.cancel_requested:
            return True
        status = await self.db.fetchval(
            "SELECT status FROM backup_jobs WHERE job_id = $1", job_id
        )
        return status in ("cancelled", "cancelled (rolled back)")

    async def finish_job(
        self,
        job_id: str,
        status: str = "completed",
        error_message: Optional[str] = None,
        final_step: Optional[str] = None,
    ):
        step = final_step or ("Completed successfully." if status == "completed" else "Failed.")
        await self.db.execute(
            """
            UPDATE backup_jobs
            SET status = $1, error_message = $2, current_step = $3
            WHERE job_id = $4
            """,
            status,
            error_message,
            step,
            job_id,
        )
        self.cancel_requested.discard(job_id)
        self.active_tasks.pop(job_id, None)

    async def execute_rollback(self, guild: Guild, rollback_data_json: str) -> int:
        """Rollback objects created during a load job."""
        try:
            items = json.loads(rollback_data_json)
        except Exception:
            return 0
        if not items:
            return 0

        deleted_count = 0
        # Delete channels and categories first, then roles
        channels_to_del = [i for i in items if i.get("type") in ("channel", "category")]
        roles_to_del = [i for i in items if i.get("type") == "role"]

        for entry in reversed(channels_to_del):
            obj_id = entry.get("id")
            chan = guild.get_channel(obj_id)
            if chan:
                try:
                    await chan.delete(reason="Backup job cancellation rollback")
                    deleted_count += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

        for entry in reversed(roles_to_del):
            obj_id = entry.get("id")
            role = guild.get_role(obj_id)
            if role:
                try:
                    await role.delete(reason="Backup job cancellation rollback")
                    deleted_count += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

        return deleted_count


    async def _create_backup_worker(
        self,
        ctx: Context,
        name: Optional[str],
        include_assets: bool,
        job_id: str,
        status_msg: Message,
    ):
        guild = ctx.guild
        backup_id = await self.get_unique_backup_id()
        backup_name = name or f"{guild.name} ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})"

        roles = [r for r in guild.roles if r != guild.default_role]
        roles.sort(key=lambda r: r.position)

        categories = list(guild.categories)
        categories.sort(key=lambda c: c.position)

        channels = [
            c
            for c in guild.channels
            if not isinstance(c, CategoryChannel)
        ]
        channels.sort(key=lambda c: c.position)

        asset_count = 0
        if include_assets:
            if guild.icon:
                asset_count += 1
            if guild.splash:
                asset_count += 1
            if guild.banner:
                asset_count += 1
            if getattr(guild, "discovery_splash", None):
                asset_count += 1
            asset_count += len(guild.emojis)
            asset_count += len(guild.stickers)

        progress_total = 1 + len(roles) + len(categories) + len(channels) + asset_count
        progress_current = 0

        await self.create_job(
            job_id=job_id,
            backup_id=backup_id,
            guild_id=guild.id,
            user_id=ctx.author.id,
            job_type="create",
            progress_total=progress_total,
            initial_step="Starting server snapshot...",
        )

        role_id_to_idx: Dict[int, int] = {}
        cat_id_to_idx: Dict[int, int] = {}
        chan_id_to_idx: Dict[int, int] = {}

        for idx, r in enumerate(roles):
            role_id_to_idx[r.id] = idx
        for idx, c in enumerate(categories):
            cat_id_to_idx[c.id] = idx
        for idx, ch in enumerate(channels):
            chan_id_to_idx[ch.id] = idx

        size_bytes = 0

        try:
            # 1. Server settings
            progress_current += 1
            await self.update_job(job_id, progress_current, "Saving server settings...")

            settings_to_save: Dict[str, str] = {
                "name": guild.name,
                "verification_level": guild.verification_level.name,
                "explicit_content_filter": guild.explicit_content_filter.name,
                "default_notifications": guild.default_notifications.name,
                "afk_timeout": str(guild.afk_timeout),
                "premium_progress_bar_enabled": str(int(bool(guild.premium_progress_bar_enabled))),
                "system_channel_flags": str(guild.system_channel_flags.value if guild.system_channel_flags else 0),
                "preferred_locale": str(guild.preferred_locale),
                "everyone_permissions": str(guild.default_role.permissions.value),
            }

            if guild.afk_channel and guild.afk_channel.id in chan_id_to_idx:
                settings_to_save["afk_channel_index"] = str(chan_id_to_idx[guild.afk_channel.id])
            if guild.system_channel and guild.system_channel.id in chan_id_to_idx:
                settings_to_save["system_channel_index"] = str(chan_id_to_idx[guild.system_channel.id])
            if getattr(guild, "rules_channel", None) and guild.rules_channel.id in chan_id_to_idx:
                settings_to_save["rules_channel_index"] = str(chan_id_to_idx[guild.rules_channel.id])
            if getattr(guild, "public_updates_channel", None) and guild.public_updates_channel.id in chan_id_to_idx:
                settings_to_save["public_updates_channel_index"] = str(chan_id_to_idx[guild.public_updates_channel.id])

            for k, v in settings_to_save.items():
                size_bytes += len(k) + len(v)
                await self.db.execute(
                    "INSERT INTO backup_settings (backup_id, key, value) VALUES ($1, $2, $3)",
                    backup_id,
                    k,
                    v,
                )

            # 2. Roles
            for idx, r in enumerate(roles):
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                    return

                progress_current += 1
                await self.update_job(job_id, progress_current, f"Saving role: @{r.name}")

                size_bytes += len(r.name) + 32
                await self.db.execute(
                    """
                    INSERT INTO backup_roles (
                        backup_id, role_index, name, color, hoist, mentionable, position, permissions, is_managed
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    backup_id,
                    idx,
                    r.name,
                    r.color.value,
                    int(r.hoist),
                    int(r.mentionable),
                    r.position,
                    r.permissions.value,
                    int(r.managed),
                )

            # 3. Categories
            for idx, cat in enumerate(categories):
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                    return

                progress_current += 1
                await self.update_job(job_id, progress_current, f"Saving category: {cat.name}")

                size_bytes += len(cat.name) + 16
                await self.db.execute(
                    """
                    INSERT INTO backup_categories (
                        backup_id, category_index, name, position
                    ) VALUES ($1, $2, $3, $4)
                    """,
                    backup_id,
                    idx,
                    cat.name,
                    cat.position,
                )

                for target, overwrite in cat.overwrites.items():
                    target_is_everyone = int(target == guild.default_role)
                    target_role_idx = role_id_to_idx.get(target.id) if isinstance(target, Role) else None
                    if target_is_everyone or target_role_idx is not None:
                        allow_val, deny_val = overwrite.pair()
                        await self.db.execute(
                            """
                            INSERT INTO backup_category_overwrites (
                                backup_id, category_index, target_role_index, target_is_everyone, allow, deny
                            ) VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            backup_id,
                            idx,
                            target_role_idx,
                            target_is_everyone,
                            allow_val.value,
                            deny_val.value,
                        )

            # 4. Channels
            for idx, ch in enumerate(channels):
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                    return

                progress_current += 1
                await self.update_job(job_id, progress_current, f"Saving channel: #{ch.name}")

                c_type = "text"
                if hasattr(ch, "is_news") and ch.is_news():
                    c_type = "announcement"
                elif isinstance(ch, getattr(discord, "ForumChannel", ())):
                    c_type = "forum"
                elif isinstance(ch, getattr(discord, "StageChannel", ())):
                    c_type = "stage"
                elif isinstance(ch, VoiceChannel):
                    c_type = "voice"

                cat_idx = cat_id_to_idx.get(ch.category_id) if ch.category_id else None
                topic = getattr(ch, "topic", None)
                nsfw = int(getattr(ch, "nsfw", False))
                slowmode = getattr(ch, "slowmode_delay", 0)
                bitrate = getattr(ch, "bitrate", None)
                user_limit = getattr(ch, "user_limit", None)

                size_bytes += len(ch.name) + (len(topic) if topic else 0) + 32
                await self.db.execute(
                    """
                    INSERT INTO backup_channels (
                        backup_id, channel_index, category_index, type, name, position,
                        topic, nsfw, slowmode_delay, bitrate, user_limit
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    backup_id,
                    idx,
                    cat_idx,
                    c_type,
                    ch.name,
                    ch.position,
                    topic,
                    nsfw,
                    slowmode,
                    bitrate,
                    user_limit,
                )

                for target, overwrite in ch.overwrites.items():
                    target_is_everyone = int(target == guild.default_role)
                    target_role_idx = role_id_to_idx.get(target.id) if isinstance(target, Role) else None
                    if target_is_everyone or target_role_idx is not None:
                        allow_val, deny_val = overwrite.pair()
                        await self.db.execute(
                            """
                            INSERT INTO backup_channel_overwrites (
                                backup_id, channel_index, target_role_index, target_is_everyone, allow, deny
                            ) VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            backup_id,
                            idx,
                            target_role_idx,
                            target_is_everyone,
                            allow_val.value,
                            deny_val.value,
                        )

            # 5. Assets (Optional)
            if include_assets:
                for asset_name, asset_obj in (
                    ("icon", guild.icon),
                    ("splash", guild.splash),
                    ("banner", guild.banner),
                    ("discovery_splash", getattr(guild, "discovery_splash", None)),
                ):
                    if asset_obj:
                        if await self.is_job_cancelled(job_id):
                            await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                            return
                        progress_current += 1
                        await self.update_job(job_id, progress_current, f"Downloading server {asset_name}...")
                        try:
                            data = await asset_obj.read()
                            size_bytes += len(data)
                            await self.db.execute(
                                "INSERT INTO backup_assets (backup_id, asset_type, data) VALUES ($1, $2, $3)",
                                backup_id,
                                asset_name,
                                data,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to read asset {asset_name}: {e}")

                for emoji in guild.emojis[:50]:
                    if await self.is_job_cancelled(job_id):
                        await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                        return
                    progress_current += 1
                    await self.update_job(job_id, progress_current, f"Downloading emoji: :{emoji.name}:")
                    try:
                        data = await emoji.read()
                        size_bytes += len(data)
                        await self.db.execute(
                            "INSERT INTO backup_emojis (backup_id, name, data) VALUES ($1, $2, $3)",
                            backup_id,
                            emoji.name,
                            data,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to read emoji {emoji.name}: {e}")

                for sticker in guild.stickers[:50]:
                    if await self.is_job_cancelled(job_id):
                        await self.finish_job(job_id, "cancelled", final_step="Creation cancelled by user.")
                        return
                    progress_current += 1
                    await self.update_job(job_id, progress_current, f"Downloading sticker: {sticker.name}")
                    try:
                        data = await sticker.read()
                        size_bytes += len(data)
                        await self.db.execute(
                            """
                            INSERT INTO backup_stickers (backup_id, name, description, emoji, data)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            backup_id,
                            sticker.name,
                            sticker.description or "",
                            sticker.emoji or "",
                            data,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to read sticker {sticker.name}: {e}")

            # Save master backup record
            await self.db.execute(
                """
                INSERT INTO backups (
                    id, owner_id, source_guild_id, source_guild_name, name, created_at,
                    includes_assets, channel_count, role_count, category_count, size_estimate_bytes
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                backup_id,
                ctx.author.id,
                guild.id,
                guild.name,
                backup_name,
                datetime.now(timezone.utc),
                int(include_assets),
                len(channels),
                len(roles),
                len(categories),
                size_bytes,
            )

            await self.finish_job(job_id, "completed", final_step="Backup created successfully.")

            size_str = self.bot.format_size(size_bytes)
            embed = discord.Embed(
                title=f"{EMOJIS.APPROVE} Backup Created Successfully",
                description=(
                    f"Backup **`{backup_id}`** has been created and saved.\n\n"
                    f"**Backup ID:** `{backup_id}`\n"
                    f"**Name:** {backup_name}\n"
                    f"**Source Server:** {guild.name} (`{guild.id}`)\n"
                    f"**Roles:** {len(roles)}\n"
                    f"**Categories:** {len(categories)}\n"
                    f"**Channels:** {len(channels)}\n"
                    f"**Assets Included:** {'Yes' if include_assets else 'No'}\n"
                    f"**Estimated Size:** {size_str}\n\n"
                    f"💡 *To restore this backup in any server where you have permissions, run:* `,backup load {backup_id}`"
                ),
                color=COLORS.approve,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Xrypton Backups | ID is required to load or delete")
            try:
                await status_msg.edit(embed=embed, view=None)
            except Exception:
                await ctx.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error during backup creation job {job_id}: {e}")
            await self.finish_job(job_id, "failed", error_message=str(e), final_step=f"Failed: {e}")
            err_embed = self.embed(
                f"{EMOJIS.DENY} Backup Creation Failed",
                f"An error occurred while creating backup `{backup_id}`:\n```{e}```",
                COLORS.deny,
            )
            try:
                await status_msg.edit(embed=err_embed, view=None)
            except Exception:
                await ctx.send(embed=err_embed)
