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


    async def _load_backup_worker(
        self,
        ctx: Context,
        backup: Dict[str, Any],
        wipe_mode: bool,
        job_id: str,
        status_msg: Message,
    ):
        guild = ctx.guild
        backup_id = backup["id"]
        warnings: List[str] = []

        roles_data = await self.get_backup_roles(backup_id)
        cats_data = await self.get_backup_categories(backup_id)
        chans_data = await self.get_backup_channels(backup_id)
        settings_data = await self.get_backup_settings(backup_id)

        cat_overwrites_data = await self.db.fetch(
            "SELECT * FROM backup_category_overwrites WHERE backup_id = $1", backup_id
        )
        chan_overwrites_data = await self.db.fetch(
            "SELECT * FROM backup_channel_overwrites WHERE backup_id = $1", backup_id
        )

        assets_data = await self.db.fetch(
            "SELECT asset_type, data FROM backup_assets WHERE backup_id = $1", backup_id
        )
        emojis_data = await self.db.fetch(
            "SELECT name, data FROM backup_emojis WHERE backup_id = $1", backup_id
        )
        stickers_data = await self.db.fetch(
            "SELECT name, description, emoji, data FROM backup_stickers WHERE backup_id = $1", backup_id
        )

        deletable_channels: List[discord.abc.GuildChannel] = []
        deletable_roles: List[Role] = []

        if wipe_mode:
            # Collect current channels and categories
            current_chans = [c for c in guild.channels if c.id != ctx.channel.id and not isinstance(c, CategoryChannel)]
            current_cats = list(guild.categories)
            deletable_channels = current_chans + current_cats

            # Collect non-managed roles below bot's top role
            bot_top = guild.me.top_role if guild.me else None
            for r in guild.roles:
                if r != guild.default_role and not r.managed:
                    if bot_top and r < bot_top:
                        deletable_roles.append(r)
                    else:
                        warnings.append(f"Could not delete role @{r.name} (higher than bot role).")

        progress_total = (
            len(deletable_channels)
            + len(deletable_roles)
            + len(roles_data)
            + len(cats_data)
            + len(chans_data)
            + len(cat_overwrites_data)
            + len(chan_overwrites_data)
            + 1  # Server settings
            + len(assets_data)
            + len(emojis_data)
            + len(stickers_data)
        )
        progress_current = 0

        await self.create_job(
            job_id=job_id,
            backup_id=backup_id,
            guild_id=guild.id,
            user_id=ctx.author.id,
            job_type="load",
            progress_total=progress_total,
            initial_step="Starting restore process...",
        )

        try:
            # STEP A: Wipe if enabled
            if wipe_mode:
                for ch in deletable_channels:
                    if await self.is_job_cancelled(job_id):
                        await self.finish_job(job_id, "cancelled", final_step="Load cancelled during wipe.")
                        return
                    progress_current += 1
                    await self.update_job(job_id, progress_current, f"Deleting existing channel: {ch.name}")
                    try:
                        await ch.delete(reason=f"Backup wipe restore {backup_id}")
                    except Exception as e:
                        warnings.append(f"Failed to delete channel #{ch.name}: {e}")
                    await asyncio.sleep(0.35)

                for r in deletable_roles:
                    if await self.is_job_cancelled(job_id):
                        await self.finish_job(job_id, "cancelled", final_step="Load cancelled during wipe.")
                        return
                    progress_current += 1
                    await self.update_job(job_id, progress_current, f"Deleting existing role: @{r.name}")
                    try:
                        await r.delete(reason=f"Backup wipe restore {backup_id}")
                    except Exception as e:
                        warnings.append(f"Failed to delete role @{r.name}: {e}")
                    await asyncio.sleep(0.35)

            # STEP B: Restore @everyone Permissions
            if "everyone_permissions" in settings_data:
                try:
                    ev_perms = Permissions(int(settings_data["everyone_permissions"]))
                    await guild.default_role.edit(permissions=ev_perms, reason=f"Backup load {backup_id}")
                except Exception as e:
                    warnings.append(f"Failed to update @everyone permissions: {e}")

            # STEP C: Restore Roles
            role_index_map: Dict[int, Role] = {}
            for r in roles_data:
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Load cancelled during role creation.")
                    return

                progress_current += 1
                role_name = r["name"]
                await self.update_job(job_id, progress_current, f"Creating role: @{role_name}")

                if r.get("is_managed"):
                    continue

                try:
                    new_role = await guild.create_role(
                        name=role_name,
                        colour=Colour(r["color"]),
                        hoist=bool(r["hoist"]),
                        mentionable=bool(r["mentionable"]),
                        permissions=Permissions(r["permissions"]),
                        reason=f"Backup restore {backup_id}",
                    )
                    role_index_map[r["role_index"]] = new_role
                    await self.update_job(
                        job_id,
                        progress_current,
                        f"Created role: @{role_name}",
                        rollback_entry={"type": "role", "id": new_role.id},
                    )
                except HTTPException as e:
                    warnings.append(f"Role @{role_name} creation failed: {e}")
                except Exception as e:
                    warnings.append(f"Role @{role_name} unexpected error: {e}")

                await asyncio.sleep(0.35)

            # STEP D: Restore Categories
            cat_index_map: Dict[int, CategoryChannel] = {}
            for cat in cats_data:
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Load cancelled during category creation.")
                    return

                progress_current += 1
                cat_name = cat["name"]
                await self.update_job(job_id, progress_current, f"Creating category: {cat_name}")

                try:
                    new_cat = await guild.create_category(
                        name=cat_name,
                        position=cat.get("position", 0),
                        reason=f"Backup restore {backup_id}",
                    )
                    cat_index_map[cat["category_index"]] = new_cat
                    await self.update_job(
                        job_id,
                        progress_current,
                        f"Created category: {cat_name}",
                        rollback_entry={"type": "category", "id": new_cat.id},
                    )
                except HTTPException as e:
                    warnings.append(f"Category {cat_name} creation failed: {e}")
                except Exception as e:
                    warnings.append(f"Category {cat_name} unexpected error: {e}")

                await asyncio.sleep(0.35)

            # STEP E: Restore Channels
            chan_index_map: Dict[int, discord.abc.GuildChannel] = {}
            for ch in chans_data:
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Load cancelled during channel creation.")
                    return

                progress_current += 1
                chan_name = ch["name"]
                chan_type = ch.get("type", "text")
                await self.update_job(job_id, progress_current, f"Creating channel: #{chan_name} ({chan_type})")

                parent_cat = cat_index_map.get(ch.get("category_index")) if ch.get("category_index") is not None else None

                try:
                    new_chan = None
                    if chan_type == "voice":
                        new_chan = await guild.create_voice_channel(
                            name=chan_name,
                            category=parent_cat,
                            bitrate=min(ch.get("bitrate") or 64000, guild.bitrate_limit),
                            user_limit=ch.get("user_limit"),
                            reason=f"Backup restore {backup_id}",
                        )
                    elif chan_type == "stage" and hasattr(guild, "create_stage_channel"):
                        new_chan = await guild.create_stage_channel(
                            name=chan_name,
                            category=parent_cat,
                            topic=ch.get("topic"),
                            bitrate=min(ch.get("bitrate") or 64000, guild.bitrate_limit),
                            user_limit=ch.get("user_limit"),
                            reason=f"Backup restore {backup_id}",
                        )
                    elif chan_type == "forum" and hasattr(guild, "create_forum_channel"):
                        new_chan = await guild.create_forum_channel(
                            name=chan_name,
                            category=parent_cat,
                            topic=ch.get("topic"),
                            nsfw=bool(ch.get("nsfw")),
                            slowmode_delay=ch.get("slowmode_delay") or 0,
                            reason=f"Backup restore {backup_id}",
                        )
                    elif chan_type == "announcement" and hasattr(guild, "create_text_channel"):
                        new_chan = await guild.create_text_channel(
                            name=chan_name,
                            category=parent_cat,
                            topic=ch.get("topic"),
                            nsfw=bool(ch.get("nsfw")),
                            slowmode_delay=ch.get("slowmode_delay") or 0,
                            news=True,
                            reason=f"Backup restore {backup_id}",
                        )
                    else:
                        new_chan = await guild.create_text_channel(
                            name=chan_name,
                            category=parent_cat,
                            topic=ch.get("topic"),
                            nsfw=bool(ch.get("nsfw")),
                            slowmode_delay=ch.get("slowmode_delay") or 0,
                            reason=f"Backup restore {backup_id}",
                        )

                    if new_chan:
                        chan_index_map[ch["channel_index"]] = new_chan
                        await self.update_job(
                            job_id,
                            progress_current,
                            f"Created channel: #{chan_name}",
                            rollback_entry={"type": "channel", "id": new_chan.id},
                        )
                except HTTPException as e:
                    warnings.append(f"Channel #{chan_name} creation failed: {e}")
                except Exception as e:
                    warnings.append(f"Channel #{chan_name} unexpected error: {e}")

                await asyncio.sleep(0.35)

            # STEP F: Apply Overwrites to Categories
            for ow in cat_overwrites_data:
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Load cancelled during overwrite application.")
                    return

                progress_current += 1
                cat_obj = cat_index_map.get(ow["category_index"])
                if not cat_obj:
                    continue

                target = guild.default_role if ow.get("target_is_everyone") else role_index_map.get(ow.get("target_role_index"))
                if target:
                    try:
                        overwrite = PermissionOverwrite.from_pair(
                            Permissions(ow["allow"]), Permissions(ow["deny"])
                        )
                        await cat_obj.set_permissions(
                            target, overwrite=overwrite, reason=f"Backup restore {backup_id}"
                        )
                    except Exception as e:
                        warnings.append(f"Category overwrite failed on {cat_obj.name}: {e}")

                await self.update_job(job_id, progress_current, f"Applying category permission overwrites...")
                await asyncio.sleep(0.2)

            # STEP G: Apply Overwrites to Channels
            for ow in chan_overwrites_data:
                if await self.is_job_cancelled(job_id):
                    await self.finish_job(job_id, "cancelled", final_step="Load cancelled during overwrite application.")
                    return

                progress_current += 1
                chan_obj = chan_index_map.get(ow["channel_index"])
                if not chan_obj:
                    continue

                target = guild.default_role if ow.get("target_is_everyone") else role_index_map.get(ow.get("target_role_index"))
                if target:
                    try:
                        overwrite = PermissionOverwrite.from_pair(
                            Permissions(ow["allow"]), Permissions(ow["deny"])
                        )
                        await chan_obj.set_permissions(
                            target, overwrite=overwrite, reason=f"Backup restore {backup_id}"
                        )
                    except Exception as e:
                        warnings.append(f"Channel overwrite failed on {chan_obj.name}: {e}")

                await self.update_job(job_id, progress_current, f"Applying channel permission overwrites...")
                await asyncio.sleep(0.2)

            # STEP H: Apply Server Settings
            progress_current += 1
            await self.update_job(job_id, progress_current, "Restoring server settings...")

            guild_edit_kwargs: Dict[str, Any] = {}
            if "name" in settings_data:
                guild_edit_kwargs["name"] = settings_data["name"]
            if "afk_timeout" in settings_data:
                try:
                    guild_edit_kwargs["afk_timeout"] = int(settings_data["afk_timeout"])
                except Exception:
                    pass
            if "verification_level" in settings_data:
                try:
                    guild_edit_kwargs["verification_level"] = getattr(
                        discord.VerificationLevel, settings_data["verification_level"], guild.verification_level
                    )
                except Exception:
                    pass
            if "explicit_content_filter" in settings_data:
                try:
                    guild_edit_kwargs["explicit_content_filter"] = getattr(
                        discord.ContentFilter, settings_data["explicit_content_filter"], guild.explicit_content_filter
                    )
                except Exception:
                    pass
            if "default_notifications" in settings_data:
                try:
                    guild_edit_kwargs["default_notifications"] = getattr(
                        discord.NotificationLevel, settings_data["default_notifications"], guild.default_notifications
                    )
                except Exception:
                    pass

            if "afk_channel_index" in settings_data:
                try:
                    afk_idx = int(settings_data["afk_channel_index"])
                    if afk_idx in chan_index_map and isinstance(chan_index_map[afk_idx], VoiceChannel):
                        guild_edit_kwargs["afk_channel"] = chan_index_map[afk_idx]
                except Exception:
                    pass

            if "system_channel_index" in settings_data:
                try:
                    sys_idx = int(settings_data["system_channel_index"])
                    if sys_idx in chan_index_map and isinstance(chan_index_map[sys_idx], TextChannel):
                        guild_edit_kwargs["system_channel"] = chan_index_map[sys_idx]
                except Exception:
                    pass

            if guild_edit_kwargs:
                try:
                    await guild.edit(reason=f"Backup restore {backup_id}", **guild_edit_kwargs)
                except Exception as e:
                    warnings.append(f"Server settings update failed: {e}")

            # STEP I: Restore Assets (if any)
            for asset in assets_data:
                a_type = asset["asset_type"]
                a_data = asset["data"]
                progress_current += 1
                await self.update_job(job_id, progress_current, f"Restoring server {a_type}...")
                try:
                    if a_type == "icon":
                        await guild.edit(icon=a_data, reason=f"Backup restore {backup_id}")
                    elif a_type == "banner":
                        await guild.edit(banner=a_data, reason=f"Backup restore {backup_id}")
                    elif a_type == "splash":
                        await guild.edit(splash=a_data, reason=f"Backup restore {backup_id}")
                except Exception as e:
                    warnings.append(f"Failed to restore {a_type}: {e}")
                await asyncio.sleep(0.5)

            for emoji_row in emojis_data:
                progress_current += 1
                await self.update_job(job_id, progress_current, f"Uploading emoji: {emoji_row['name']}...")
                try:
                    await guild.create_custom_emoji(
                        name=emoji_row["name"],
                        image=emoji_row["data"],
                        reason=f"Backup restore {backup_id}",
                    )
                except Exception as e:
                    warnings.append(f"Failed to upload emoji {emoji_row['name']}: {e}")
                await asyncio.sleep(0.5)

            for sticker_row in stickers_data:
                progress_current += 1
                await self.update_job(job_id, progress_current, f"Uploading sticker: {sticker_row['name']}...")
                try:
                    file = discord.File(io.BytesIO(sticker_row["data"]), filename=f"{sticker_row['name']}.png")
                    await guild.create_sticker(
                        name=sticker_row["name"],
                        description=sticker_row["description"] or "Restored sticker",
                        emoji=sticker_row["emoji"] or "⭐",
                        file=file,
                        reason=f"Backup restore {backup_id}",
                    )
                except Exception as e:
                    warnings.append(f"Failed to upload sticker {sticker_row['name']}: {e}")
                await asyncio.sleep(0.5)

            # Cleanup wipe invocation channel if needed
            if wipe_mode and ctx.channel.id != getattr(guild.system_channel, "id", None):
                # If we wiped, we left ctx.channel alive so messages could be sent.
                # Now we can leave a pointer or remove it if other channels exist.
                pass

            await self.finish_job(job_id, "completed", final_step="Restore completed successfully.")

            warning_text = ""
            if warnings:
                warning_text = f"\n\n⚠️ **Notices ({len(warnings)}):**\n" + "\n".join(f"• {w}" for w in warnings[:5])
                if len(warnings) > 5:
                    warning_text += f"\n*...and {len(warnings) - 5} more*"

            embed = discord.Embed(
                title=f"{EMOJIS.APPROVE} Backup Restored Successfully",
                description=(
                    f"Backup **`{backup_id}`** has been fully restored to **{guild.name}**.\n\n"
                    f"**Mode:** {'Wipe & Restore' if wipe_mode else 'Additive (Existing Retained)'}\n"
                    f"**Roles Created:** {len(role_index_map)}/{len(roles_data)}\n"
                    f"**Categories Created:** {len(cat_index_map)}/{len(cats_data)}\n"
                    f"**Channels Created:** {len(chan_index_map)}/{len(chans_data)}\n"
                    f"**Overwrites Applied:** {len(cat_overwrites_data) + len(chan_overwrites_data)}"
                    f"{warning_text}"
                ),
                color=COLORS.approve,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Xrypton Backups | Restore complete")
            try:
                await status_msg.edit(embed=embed, view=None)
            except Exception:
                await ctx.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error during backup restore job {job_id}: {e}")
            await self.finish_job(job_id, "failed", error_message=str(e), final_step=f"Failed: {e}")
            err_embed = self.embed(
                f"{EMOJIS.DENY} Backup Restore Failed",
                f"An error occurred while restoring backup `{backup_id}`:\n```{e}```\n\n"
                f"💡 *If you need to rollback created objects, run:* `,backup cancel {job_id} --rollback`",
                COLORS.deny,
            )
            try:
                await status_msg.edit(embed=err_embed, view=None)
            except Exception:
                await ctx.send(embed=err_embed)


    # =========================================================================
    # COMMANDS
    # =========================================================================

    @example(",backup")
    @hybrid_group(
        name="backup",
        aliases=["bk"],
        invoke_without_command=True,
        description="Create, load, inspect, and manage server backups",
    )
    async def backup(self, ctx: Context):
        """Display the backup system overview and available commands."""
        embed = self.embed(
            f"📦 Xrypton Backup System",
            (
                "Create, restore, and manage full server templates and configurations.\n\n"
                "**Available Commands:**\n"
                "• `,backup create [name]` — Snapshot current server structure & settings\n"
                "• `,backup load <id> [--wipe]` — Restore a backup (additive or wipe mode)\n"
                "• `,backup info [id]` — Detailed backup stats & visual channel/role tree\n"
                "• `,backup list` — List all your saved backups\n"
                "• `,backup delete <id>` — Permanently delete a saved backup\n"
                "• `,backup status [job_id]` — View live progress of running operations\n"
                "• `,backup cancel <id> [--rollback]` — Abort a running job (with optional rollback)\n"
                "• `,backup diff <id>` — Compare a backup against the current server\n"
                "• `,backup export <id>` — Export backup configuration to a JSON file\n\n"
                "🔒 **Ownership & Security:**\n"
                "Backups are tied to your Discord account. Only you can load, view, or delete your backups.\n\n"
                "⚠️ **v1 Scope & Limitations:**\n"
                "Message history, member lists/member-role assignments, and guild ban lists are out of scope for v1."
            ),
        )
        embed.add_field(
            name="Required Bot Permissions",
            value="`Manage Server`, `Manage Channels`, `Manage Roles`, `Manage Expressions`",
            inline=False,
        )
        return await ctx.send(embed=embed)

    @example(",backup create MyServerBackup")
    @backup.command(name="create", aliases=["new", "save"], description="Create a new server backup")
    @has_permissions(manage_guild=True)
    async def backup_create(self, ctx: Context, *, name: Optional[str] = None):
        """Create a full snapshot of the current server."""
        if not ctx.guild:
            return await ctx.warn("This command can only be used inside a server.")

        prompt_embed = self.embed(
            "📦 Create Server Backup",
            (
                f"Preparing to backup **{ctx.guild.name}**.\n\n"
                "Choose backup mode:\n"
                "• **Include Assets**: Downloads icons, splash, banners, emojis, and stickers.\n"
                "• **Structure Only**: Fast snapshot of roles, categories, channels, permissions & settings.\n\n"
                "Select an option below to begin:"
            ),
        )
        view = AssetPromptView(ctx)
        msg = await ctx.send(embed=prompt_embed, view=view)

        await view.wait()
        if view.cancelled or view.include_assets is None:
            cancel_embed = self.embed("Backup Cancelled", "Backup creation was aborted.", COLORS.warn)
            return await msg.edit(embed=cancel_embed, view=None)

        job_id = generate_job_id()
        init_embed = self.embed(
            f"{EMOJIS.LOADING} Creating Server Backup...",
            f"Job ID: `{job_id}`\nMode: **{'Assets Included' if view.include_assets else 'Structure Only'}**\n\nStarting snapshot...",
            COLORS.neutral,
        )
        await msg.edit(embed=init_embed, view=None)

        task = asyncio.create_task(
            self._create_backup_worker(
                ctx=ctx,
                name=name,
                include_assets=view.include_assets,
                job_id=job_id,
                status_msg=msg,
            )
        )
        self.active_tasks[job_id] = task

    @example(",backup load ABCDEF")
    @backup.command(name="load", aliases=["restore", "apply"], description="Restore a server backup")
    @has_permissions(manage_guild=True)
    async def backup_load(self, ctx: Context, backup_id: str, *, flags: Optional[str] = ""):
        """Load and restore a saved server backup."""
        if not ctx.guild:
            return await ctx.warn("This command can only be used inside a server.")

        combined_args = f"{backup_id} {flags or ''}".strip().split()
        clean_id = combined_args[0].upper()
        wipe_mode = any(arg.lower() in ("--wipe", "-wipe", "wipe") for arg in combined_args[1:])

        backup = await self.get_backup(clean_id)
        if not backup:
            return await ctx.deny(f"No backup found with ID **`{clean_id}`**.")

        # Ownership check
        if backup["owner_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You do not own this backup. Backups can only be loaded by their creator.")

        roles_data = await self.get_backup_roles(clean_id)
        cats_data = await self.get_backup_categories(clean_id)
        chans_data = await self.get_backup_channels(clean_id)

        # Generate monospace preview
        tree_chunks = render_channel_tree_chunks(chans_data, cats_data, max_chunk_chars=1200)
        tree_preview = tree_chunks[0] if tree_chunks else "```\n(No channels)\n```"
        if len(tree_chunks) > 1:
            tree_preview += f"\n*...and {len(tree_chunks) - 1} more page(s) of channels*"

        created_ts = int(backup["created_at"].timestamp()) if isinstance(backup["created_at"], datetime) else int(time.time())

        # WIPE MODE FLOW
        if wipe_mode:
            if not ctx.author.guild_permissions.administrator and ctx.author.id != ctx.guild.owner_id and ctx.author.id not in ctx.bot.owner_ids:
                return await ctx.deny("You need **Administrator** permission in this server to use `--wipe` mode.")

            del_chans_count = len([c for c in ctx.guild.channels if not isinstance(c, CategoryChannel)])
            del_cats_count = len(ctx.guild.categories)
            bot_top = ctx.guild.me.top_role if ctx.guild.me else None
            del_roles_count = len([r for r in ctx.guild.roles if r != ctx.guild.default_role and not r.managed and (not bot_top or r < bot_top)])

            danger_embed = discord.Embed(
                title="⚠️ DANGER: Server Wipe & Restore Confirmation",
                description=(
                    f"You are about to restore backup **`{clean_id}`** ({backup['name']}) into **{ctx.guild.name}** using **`--wipe` mode**.\n\n"
                    f"🚨 **This will PERMANENTLY DELETE:**\n"
                    f"• **{del_chans_count}** Channels\n"
                    f"• **{del_cats_count}** Categories\n"
                    f"• **{del_roles_count}** Roles\n\n"
                    f"**What will NOT be deleted:**\n"
                    f"• `@everyone` role (permissions will be overwritten)\n"
                    f"• Managed bot & integration roles\n\n"
                    f"⚠️ **Rollback Limitation:** If cancelled partway through, deleted channels/roles cannot be restored by rollback.\n\n"
                    f"**Structure Preview to Restore:**\n{tree_preview}\n\n"
                    f"Click **Proceed to Verification** and type `{ctx.guild.name}` or `{clean_id}` to proceed."
                ),
                color=COLORS.red,
            )
            danger_embed.set_footer(text="Xrypton Backups | Two-Step Destructive Action Verification")

            view = WipeConfirmView(ctx, clean_id)
            msg = await ctx.send(embed=danger_embed, view=view)

            await view.wait()
            if not view.confirmed:
                cancel_embed = self.embed("Wipe Load Cancelled", "Server wipe was cancelled. No changes were made.", COLORS.neutral)
                return await msg.edit(embed=cancel_embed, view=None)

            job_id = generate_job_id()
            load_init_embed = self.embed(
                f"{EMOJIS.LOADING} Wiping and Restoring Backup...",
                f"Job ID: `{job_id}`\nBackup: `{clean_id}`\nTarget Server: **{ctx.guild.name}**\n\nInitializing restore pipeline...",
                COLORS.neutral,
            )
            await msg.edit(embed=load_init_embed, view=None)

            task = asyncio.create_task(
                self._load_backup_worker(
                    ctx=ctx,
                    backup=backup,
                    wipe_mode=True,
                    job_id=job_id,
                    status_msg=msg,
                )
            )
            self.active_tasks[job_id] = task

        # STANDARD ADDITIVE LOAD FLOW
        else:
            additive_embed = discord.Embed(
                title=f"📦 Backup Load Preview — `{clean_id}`",
                description=(
                    f"Target Server: **{ctx.guild.name}** (`{ctx.guild.id}`)\n"
                    f"Source Server: **{backup['source_guild_name']}**\n"
                    f"Created: <t:{created_ts}:R>\n\n"
                    f"ℹ️ **Additive Mode**: This will create **{len(roles_data)} roles**, "
                    f"**{len(cats_data)} categories**, and **{len(chans_data)} channels** in this server.\n"
                    f"Existing channels and roles will **not** be touched or deleted.\n\n"
                    f"**Structure Preview:**\n{tree_preview}"
                ),
                color=COLORS.information,
            )
            additive_embed.set_footer(text="Xrypton Backups | Confirm to proceed")

            view = LoadConfirmView(ctx)
            msg = await ctx.send(embed=additive_embed, view=view)

            await view.wait()
            if not view.confirmed:
                cancel_embed = self.embed("Load Cancelled", "Backup restore was cancelled.", COLORS.neutral)
                return await msg.edit(embed=cancel_embed, view=None)

            job_id = generate_job_id()
            load_init_embed = self.embed(
                f"{EMOJIS.LOADING} Restoring Backup...",
                f"Job ID: `{job_id}`\nBackup: `{clean_id}`\nTarget Server: **{ctx.guild.name}**\n\nInitializing restore pipeline...",
                COLORS.neutral,
            )
            await msg.edit(embed=load_init_embed, view=None)

            task = asyncio.create_task(
                self._load_backup_worker(
                    ctx=ctx,
                    backup=backup,
                    wipe_mode=False,
                    job_id=job_id,
                    status_msg=msg,
                )
            )
            self.active_tasks[job_id] = task

    @example(",backup info ABCDEF")
    @backup.command(name="info", aliases=["view", "show"], description="View detailed backup information and structure")
    async def backup_info(self, ctx: Context, backup_id: Optional[str] = None):
        """View detailed stats and illustrated tree preview for a backup."""
        if not backup_id:
            return await self.backup_list(ctx)

        clean_id = backup_id.upper()
        backup = await self.get_backup(clean_id)
        if not backup:
            return await ctx.deny(f"No backup found with ID **`{clean_id}`**.")

        if backup["owner_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You do not own this backup.")

        roles_data = await self.get_backup_roles(clean_id)
        cats_data = await self.get_backup_categories(clean_id)
        chans_data = await self.get_backup_channels(clean_id)
        settings_data = await self.get_backup_settings(clean_id)

        created_ts = int(backup["created_at"].timestamp()) if isinstance(backup["created_at"], datetime) else int(time.time())
        size_str = self.bot.format_size(backup.get("size_estimate_bytes", 0))

        tree_chunks = render_channel_tree_chunks(chans_data, cats_data)
        role_chunks = render_role_list_chunks(roles_data)

        embeds: List[Embed] = []

        # Page 1: Overview
        p1 = discord.Embed(
            title=f"📦 Backup Overview — `{clean_id}`",
            description=(
                f"**Name:** {backup['name']}\n"
                f"**Backup ID:** `{clean_id}`\n"
                f"**Owner:** <@{backup['owner_id']}> (`{backup['owner_id']}`)\n"
                f"**Source Server:** {backup['source_guild_name']} (`{backup['source_guild_id']}`)\n"
                f"**Created At:** <t:{created_ts}:F> (<t:{created_ts}:R>)\n"
                f"**Assets Included:** {'Yes' if backup.get('includes_assets') else 'No'}\n"
                f"**Estimated Size:** {size_str}\n\n"
                f"**Structure Statistics:**\n"
                f"• Roles: `{len(roles_data)}`\n"
                f"• Categories: `{len(cats_data)}`\n"
                f"• Channels: `{len(chans_data)}`\n"
                f"• Verification Level: `{settings_data.get('verification_level', 'Default')}`\n"
                f"• Content Filter: `{settings_data.get('explicit_content_filter', 'Default')}`"
            ),
            color=COLORS.neutral,
        )
        p1.set_footer(text=f"Xrypton Backups | Page 1/{1 + len(tree_chunks) + len(role_chunks)}")
        embeds.append(p1)

        # Channel Tree Pages
        for idx, chunk in enumerate(tree_chunks, start=1):
            pe = discord.Embed(
                title=f"📁 Channel Structure — `{clean_id}`",
                description=f"Showing channel hierarchy ({idx}/{len(tree_chunks)}):\n{chunk}",
                color=COLORS.neutral,
            )
            pe.set_footer(text=f"Xrypton Backups | Page {len(embeds) + 1}/{1 + len(tree_chunks) + len(role_chunks)}")
            embeds.append(pe)

        # Role Hierarchy Pages
        for idx, chunk in enumerate(role_chunks, start=1):
            re_embed = discord.Embed(
                title=f"🛡️ Role Hierarchy — `{clean_id}`",
                description=f"Showing roles hierarchy ({idx}/{len(role_chunks)}):\n{chunk}",
                color=COLORS.neutral,
            )
            re_embed.set_footer(text=f"Xrypton Backups | Page {len(embeds) + 1}/{1 + len(tree_chunks) + len(role_chunks)}")
            embeds.append(re_embed)

        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await ctx.paginate(embeds)

    @example(",backup list")
    @backup.command(name="list", aliases=["all"], description="List all of your saved backups")
    async def backup_list(self, ctx: Context):
        """List all backups owned by you, paginated and sorted newest first."""
        rows = await self.db.fetch(
            "SELECT * FROM backups WHERE owner_id = $1 ORDER BY created_at DESC",
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn(
                f"You have no saved backups yet.\nCreate one with `{ctx.clean_prefix}backup create`!"
            )

        entries = []
        for i, b in enumerate(rows, start=1):
            created_ts = int(b["created_at"].timestamp()) if isinstance(b["created_at"], datetime) else int(time.time())
            size_str = self.bot.format_size(b.get("size_estimate_bytes", 0))
            entries.append(
                f"`{i}.` **`{b['id']}`** — **{b['name']}**\n"
                f"└ Source: *{b['source_guild_name']}* • Created: <t:{created_ts}:R>\n"
                f"└ Stats: `{b.get('role_count', 0)}` roles, `{b.get('channel_count', 0)}` channels • Size: `{size_str}`"
            )

        embeds: List[Embed] = []
        page_size = 5
        total_pages = (len(entries) + page_size - 1) // page_size

        for page_idx in range(total_pages):
            page_entries = entries[page_idx * page_size : (page_idx + 1) * page_size]
            emb = discord.Embed(
                title=f"📦 Your Saved Backups ({len(rows)})",
                description="\n\n".join(page_entries),
                color=COLORS.neutral,
            )
            emb.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            emb.set_footer(text=f"Xrypton Backups | Page {page_idx + 1}/{total_pages} • Total: {len(rows)}")
            embeds.append(emb)

        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await ctx.paginate(embeds)

    @example(",backup delete ABCDEF")
    @backup.command(name="delete", aliases=["remove", "del"], description="Permanently delete a backup")
    async def backup_delete(self, ctx: Context, backup_id: str):
        """Permanently delete a backup and all associated data."""
        clean_id = backup_id.upper()
        backup = await self.get_backup(clean_id)
        if not backup:
            return await ctx.deny(f"No backup found with ID **`{clean_id}`**.")

        if backup["owner_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You do not own this backup.")

        confirm_embed = self.embed(
            f"🗑️ Delete Backup `{clean_id}`?",
            (
                f"Are you sure you want to permanently delete backup **`{clean_id}`** ({backup['name']})?\n\n"
                f"⚠️ **This action is irreversible.** All role data, channel trees, and saved assets will be wiped."
            ),
            COLORS.warn,
        )
        view = DeleteConfirmView(ctx, clean_id)
        msg = await ctx.send(embed=confirm_embed, view=view)

        await view.wait()
        if not view.confirmed:
            cancel_embed = self.embed("Deletion Cancelled", f"Backup `{clean_id}` was not deleted.", COLORS.neutral)
            return await msg.edit(embed=cancel_embed, view=None)

        await self.delete_backup_data(clean_id)
        success_embed = self.embed(
            f"{EMOJIS.APPROVE} Backup Deleted",
            f"Backup **`{clean_id}`** has been permanently removed.",
            COLORS.approve,
        )
        return await msg.edit(embed=success_embed, view=None)

    @example(",backup status")
    @backup.command(name="status", aliases=["progress", "job"], description="Check status of running backup operations")
    async def backup_status(self, ctx: Context, job_id: Optional[str] = None):
        """Display live progress and step details for running backup operations."""
        if job_id:
            job = await self.db.fetchrow("SELECT * FROM backup_jobs WHERE job_id = $1", job_id.upper())
            if not job:
                return await ctx.deny(f"No job found with ID **`{job_id}`**.")
        else:
            job = await self.db.fetchrow(
                "SELECT * FROM backup_jobs WHERE user_id = $1 AND status = 'running' ORDER BY started_at DESC LIMIT 1",
                ctx.author.id,
            )
            if not job:
                job = await self.db.fetchrow(
                    "SELECT * FROM backup_jobs WHERE user_id = $1 ORDER BY started_at DESC LIMIT 1",
                    ctx.author.id,
                )
            if not job:
                return await ctx.warn("You have no active or recent backup jobs.")

        cur = job["progress_current"] or 0
        tot = job["progress_total"] or 0
        bar = format_progress_bar(cur, tot)
        started_ts = int(job["started_at"].timestamp()) if isinstance(job["started_at"], datetime) else int(time.time())

        status_color = COLORS.neutral
        if job["status"] == "completed":
            status_color = COLORS.approve
        elif "cancelled" in job["status"]:
            status_color = COLORS.warn
        elif job["status"] == "failed":
            status_color = COLORS.deny

        embed = discord.Embed(
            title=f"📊 Backup Job Status — `{job['job_id']}`",
            description=(
                f"**Type:** `{job['job_type'].upper()}`\n"
                f"**Status:** **{job['status'].upper()}**\n"
                f"**Backup ID:** `{job['backup_id'] or 'N/A'}`\n"
                f"**Started:** <t:{started_ts}:R>\n\n"
                f"**Progress:** {bar}\n"
                f"**Current Step:** {job['current_step'] or 'N/A'}"
                f"{f'''\n**Error:** ```{job['error_message']}```''' if job['error_message'] else ''}"
            ),
            color=status_color,
        )
        embed.set_footer(text=f"Xrypton Backups | Job ID: {job['job_id']}")
        return await ctx.send(embed=embed)

    @example(",backup cancel J123456 --rollback")
    @backup.command(name="cancel", aliases=["stop", "abort"], description="Cancel a running backup job")
    async def backup_cancel(self, ctx: Context, identifier: str, *, flags: Optional[str] = ""):
        """Cancel a running backup job with optional --rollback flag."""
        combined = f"{identifier} {flags or ''}".strip().split()
        target_id = combined[0].upper()
        do_rollback = any(arg.lower() in ("--rollback", "-rollback", "rollback") for arg in combined[1:])

        # Find job by job_id or backup_id
        job = await self.db.fetchrow(
            "SELECT * FROM backup_jobs WHERE (job_id = $1 OR backup_id = $1) AND status = 'running' LIMIT 1",
            target_id,
        )
        if not job:
            job = await self.db.fetchrow(
                "SELECT * FROM backup_jobs WHERE job_id = $1 OR backup_id = $1 ORDER BY started_at DESC LIMIT 1",
                target_id,
            )
            if not job:
                return await ctx.deny(f"No job found matching **`{target_id}`**.")
            if job["status"] != "running":
                return await ctx.warn(f"Job `{job['job_id']}` is already **{job['status']}**.")

        if job["user_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You can only cancel your own backup jobs.")

        self.cancel_requested.add(job["job_id"])
        await self.db.execute("UPDATE backup_jobs SET status = 'cancelled' WHERE job_id = $1", job["job_id"])

        task = self.active_tasks.get(job["job_id"])
        if task and not task.done():
            task.cancel()

        rolled_back_count = 0
        if do_rollback and ctx.guild and job.get("rollback_data"):
            rolled_back_count = await self.execute_rollback(ctx.guild, job["rollback_data"])
            await self.db.execute(
                "UPDATE backup_jobs SET status = 'cancelled (rolled back)' WHERE job_id = $1",
                job["job_id"],
            )

        msg_text = f"Cancelled backup job **`{job['job_id']}`**."
        if do_rollback:
            msg_text += f"\nRolled back **{rolled_back_count}** newly created Discord objects."

        return await ctx.approve(msg_text)

    @example(",backup diff ABCDEF")
    @backup.command(name="diff", description="Compare a saved backup against the current server")
    @has_permissions(manage_guild=True)
    async def backup_diff(self, ctx: Context, backup_id: str):
        """Compare backup structure against the live server state."""
        clean_id = backup_id.upper()
        backup = await self.get_backup(clean_id)
        if not backup:
            return await ctx.deny(f"No backup found with ID **`{clean_id}`**.")

        if backup["owner_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You do not own this backup.")

        backup_roles = await self.get_backup_roles(clean_id)
        backup_chans = await self.get_backup_channels(clean_id)
        backup_cats = await self.get_backup_categories(clean_id)

        live_roles = {r.name.lower(): r for r in ctx.guild.roles if r != ctx.guild.default_role}
        live_chans = {c.name.lower(): c for c in ctx.guild.channels if not isinstance(c, CategoryChannel)}
        live_cats = {c.name.lower(): c for c in ctx.guild.categories}

        bk_role_names = {r["name"].lower() for r in backup_roles if not r.get("is_managed")}
        bk_chan_names = {c["name"].lower() for c in backup_chans}
        bk_cat_names = {c["name"].lower() for c in backup_cats}

        roles_to_add = bk_role_names - set(live_roles.keys())
        roles_existing = bk_role_names & set(live_roles.keys())
        chans_to_add = bk_chan_names - set(live_chans.keys())
        chans_existing = bk_chan_names & set(live_chans.keys())
        cats_to_add = bk_cat_names - set(live_cats.keys())

        diff_lines = [
            f"=== DIFF: Backup {clean_id} vs {ctx.guild.name} ===",
            "",
            f"Roles in Backup: {len(bk_role_names)} | Roles in Live Server: {len(live_roles)}",
            f"  + Missing Roles to Add ({len(roles_to_add)}): {', '.join(list(roles_to_add)[:6]) or 'None'}",
            f"  = Matching Roles ({len(roles_existing)})",
            "",
            f"Categories in Backup: {len(bk_cat_names)} | Categories in Live Server: {len(live_cats)}",
            f"  + Missing Categories to Add ({len(cats_to_add)}): {', '.join(list(cats_to_add)[:6]) or 'None'}",
            "",
            f"Channels in Backup: {len(bk_chan_names)} | Channels in Live Server: {len(live_chans)}",
            f"  + Missing Channels to Add ({len(chans_to_add)}): {', '.join(list(chans_to_add)[:6]) or 'None'}",
            f"  = Matching Channels ({len(chans_existing)})",
        ]

        diff_block = "```diff\n" + "\n".join(diff_lines) + "\n```"
        embed = self.embed(f"🔍 Backup Difference Analysis — `{clean_id}`", diff_block, COLORS.information)
        return await ctx.send(embed=embed)

    @example(",backup export ABCDEF")
    @backup.command(name="export", description="Export a backup configuration to a JSON file")
    async def backup_export(self, ctx: Context, backup_id: str):
        """Export full backup metadata and schema structure as a JSON file."""
        clean_id = backup_id.upper()
        backup = await self.get_backup(clean_id)
        if not backup:
            return await ctx.deny(f"No backup found with ID **`{clean_id}`**.")

        if backup["owner_id"] != ctx.author.id and ctx.author.id not in ctx.bot.owner_ids:
            return await ctx.deny("You do not own this backup.")

        roles_data = await self.get_backup_roles(clean_id)
        cats_data = await self.get_backup_categories(clean_id)
        chans_data = await self.get_backup_channels(clean_id)
        settings_data = await self.get_backup_settings(clean_id)

        export_dict = {
            "backup_id": clean_id,
            "name": backup["name"],
            "owner_id": backup["owner_id"],
            "source_guild": {
                "id": backup["source_guild_id"],
                "name": backup["source_guild_name"],
            },
            "created_at": backup["created_at"].isoformat() if isinstance(backup["created_at"], datetime) else str(backup["created_at"]),
            "settings": settings_data,
            "roles": roles_data,
            "categories": cats_data,
            "channels": chans_data,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        json_bytes = json.dumps(export_dict, indent=2).encode("utf-8")
        file = discord.File(io.BytesIO(json_bytes), filename=f"xrypton_backup_{clean_id}.json")

        return await ctx.send(
            content=f"{EMOJIS.APPROVE} Exported backup **`{clean_id}`** configuration:",
            file=file,
        )
