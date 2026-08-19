"""Centralized moderation action logger for Xrypton.

Called by moderation commands in cogs/moderation/moderation.py and dispatched
to the moderation-logs channel handled by cogs/logging/logging.py.
"""
from typing import Optional, Union, Dict, Any
import discord
from discord.ext import commands


async def log_moderation_action(
    bot: commands.Bot,
    guild: discord.Guild,
    action: str,
    moderator: Union[discord.Member, discord.User],
    target: Union[discord.Member, discord.User, discord.abc.GuildChannel, discord.Role, str],
    reason: Optional[str] = None,
    duration: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Centralized hook for moderation punishment logging.

    Dispatches a 'moderation_action' event which cogs/logging/logging.py listens for,
    and directly informs the Logging cog if loaded.
    """
    clean_reason = reason or "No reason provided."
    # Strip any bot-appended "| Executed by ..." if present to avoid clutter
    if " | Executed by " in clean_reason:
        clean_reason = clean_reason.split(" | Executed by ")[0].strip()

    bot.dispatch(
        "moderation_action",
        guild,
        action,
        moderator,
        target,
        clean_reason,
        duration,
        extra or {},
    )

    logging_cog = bot.get_cog("Logging")
    if logging_cog is not None and hasattr(logging_cog, "handle_moderation_action"):
        try:
            await logging_cog.handle_moderation_action(
                guild=guild,
                action=action,
                moderator=moderator,
                target=target,
                reason=clean_reason,
                duration=duration,
                extra=extra or {},
            )
        except Exception:
            pass
