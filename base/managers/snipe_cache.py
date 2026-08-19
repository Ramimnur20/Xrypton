"""Shared snipe and message cache utility for Xrypton.

Shared between cogs/moderation/snipe.py and cogs/logging/logging.py so that
message delete / edit cache is centralized and not duplicated.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import discord

# Central shared dictionaries
Sniped: Dict[int, List[Dict[str, Any]]] = {}
editSnipe: Dict[int, List[Dict[str, Any]]] = {}
reactSnipe: Dict[int, List[Dict[str, Any]]] = {}
rawMessageCache: Dict[int, Dict[str, Any]] = {}  # message_id -> message snapshot for uncached deletes

MAX_CACHE_PER_CHANNEL = 50
MAX_RAW_MESSAGES = 2000


def record_raw_message(message: discord.Message) -> None:
    """Cache recent message info in case discord.py gateway cache drops it before delete/edit."""
    if message.author.bot:
        return
    if len(rawMessageCache) > MAX_RAW_MESSAGES:
        # Purge oldest entries
        keys = list(rawMessageCache.keys())[:200]
        for k in keys:
            rawMessageCache.pop(k, None)

    image_url = message.attachments[0].url if message.attachments else None
    rawMessageCache[message.id] = {
        "id": message.id,
        "guild_id": message.guild.id if message.guild else None,
        "channel_id": message.channel.id,
        "author": str(message.author),
        "author_id": message.author.id,
        "author_url": str(message.author.display_avatar.url),
        "content": message.content or "",
        "attachments": [a.url for a in message.attachments],
        "image_url": image_url,
        "created_at": message.created_at,
        "has_attachments": bool(message.attachments),
        "has_stickers": bool(getattr(message, "stickers", None)),
        "has_poll": bool(getattr(message, "poll", None)),
    }


def record_delete(
    channel_id: int,
    author: str,
    author_url: str,
    content: str,
    image_url: Optional[str] = None,
    created_at: Optional[datetime] = None,
    deleted_at: Optional[datetime] = None,
    author_id: Optional[int] = None,
    message_id: Optional[int] = None,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a deleted message in the shared Sniped cache."""
    if channel_id not in Sniped:
        Sniped[channel_id] = []

    now = deleted_at or datetime.now(timezone.utc)
    entry = {
        "author": author,
        "author_id": author_id,
        "author_url": author_url,
        "content": content,
        "image_url": image_url,
        "attachments": attachments or ([] if not image_url else [image_url]),
        "timestamp": created_at or now,
        "deleted_at": now,
        "message_id": message_id,
    }
    Sniped[channel_id].insert(0, entry)
    if len(Sniped[channel_id]) > MAX_CACHE_PER_CHANNEL:
        Sniped[channel_id].pop()
    return entry


def record_edit(
    channel_id: int,
    author: str,
    author_url: str,
    before_content: str,
    after_content: str,
    author_id: Optional[int] = None,
    message_id: Optional[int] = None,
    created_at: Optional[datetime] = None,
    edited_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record an edited message in the shared editSnipe cache."""
    if channel_id not in editSnipe:
        editSnipe[channel_id] = []

    now = edited_at or datetime.now(timezone.utc)
    entry = {
        "author": author,
        "author_id": author_id,
        "author_url": author_url,
        "before_content": before_content,
        "after_content": after_content,
        "timestamp": created_at or now,
        "edited_at": now,
        "message_id": message_id,
    }
    editSnipe[channel_id].insert(0, entry)
    if len(editSnipe[channel_id]) > MAX_CACHE_PER_CHANNEL:
        editSnipe[channel_id].pop()
    return entry


def record_reaction_remove(
    channel_id: int,
    guild_id: int,
    user_id: int,
    emoji: str,
    message_id: int,
    timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record a removed reaction in the shared reactSnipe cache."""
    if channel_id not in reactSnipe:
        reactSnipe[channel_id] = []

    now = timestamp or datetime.now(timezone.utc)
    message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    entry = {
        "author": str(user_id),
        "emoji": emoji,
        "message_link": message_link,
        "message_id": message_id,
        "timestamp": now,
    }
    reactSnipe[channel_id].insert(0, entry)
    if len(reactSnipe[channel_id]) > MAX_CACHE_PER_CHANNEL:
        reactSnipe[channel_id].pop()
    return entry


def clear_channel_snipes(channel_id: int) -> bool:
    """Clear all snipes for a channel. Returns True if anything was cleared."""
    cleared = False
    if channel_id in Sniped:
        del Sniped[channel_id]
        cleared = True
    if channel_id in editSnipe:
        del editSnipe[channel_id]
        cleared = True
    if channel_id in reactSnipe:
        del reactSnipe[channel_id]
        cleared = True
    return cleared
