"""
Starboard — repost popular messages to a starboard channel based on ⭐ reactions.

Commands (single `starboard` group, manage_guild required):
    starboard channel <channel>  — set the starboard channel
    starboard threshold <n>      — set the star threshold (default 3)
    starboard emoji <emoji>      — set the trigger emji (default ⭐)
    starboard ignore <channel>   — ignore a channel (no starring from it)
    starboard unignore <channel> — stop ignoring a channel
    starboard disable            — turn the starboard off
    starboard config             — show current config
"""

from __future__ import annotations

import json

import discord
from discord.ext import commands

from base.managers.predicates import example
from base.config import EMOJIS


MESSAGES = {
    "channel_set":   f"{EMOJIS.APPROVE} Starboard channel set to **{{channel}}**.",
    "threshold_set": f"{EMOJIS.APPROVE} Star threshold set to **{{n}}**.",
    "emoji_set":     f"{EMOJIS.APPROVE} Starboard emoji set to **{{emoji}}**.",
    "ignored":       f"{EMOJIS.APPROVE} Now ignoring **{{channel}}**.",
    "unignored":     f"{EMOJIS.APPROVE} No longer ignoring **{{channel}}**.",
    "disabled":      f"{EMOJIS.APPROVE} Starboard disabled.",
    "invalid_threshold": f"{EMOJIS.DENY} Threshold must be between **1** and **50**.",
    "channel_missing":   f"{EMOJIS.WARN} No starboard channel configured.",
    "config_title":  None,
    "config_body":   None,
    "starred":       "{emoji} **{count}** · {channel}",
}


class Starboard(commands.Cog):
    """Star-based highlight wall for popular messages."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.pool.execute("""
            CREATE TABLE IF NOT EXISTS starboard_guilds (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER DEFAULT 0,
                threshold INTEGER DEFAULT 3,
                emoji TEXT DEFAULT '⭐',
                ignored_channels TEXT DEFAULT '[]'
            )
        """)
        await self.bot.pool.execute("""
            CREATE TABLE IF NOT EXISTS starred_messages (
                guild_id INTEGER,
                message_id INTEGER,
                starboard_message_id INTEGER,
                PRIMARY KEY (guild_id, message_id)
            )
        """)

    @commands.hybrid_group(
        name="starboard",
        description="Starboard configuration.",
        invoke_without_command=True,
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    @example(",starboard")
    async def starboard(self, ctx: commands.Context):
        await ctx.send_help(self.starboard)

    @starboard.command(
        name="channel",
        description="Set the starboard channel.",
    )
    @example(",starboard channel #starboard")
    async def starboard_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.pool.execute(
            "INSERT INTO starboard_guilds (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2",
            ctx.guild.id, channel.id,
        )
        await ctx.approve(MESSAGES["channel_set"].format(channel=channel.mention))

    @starboard.command(
        name="threshold",
        description="Set the star threshold (1–50).",
    )
    @example(",starboard threshold 5")
    async def starboard_threshold(self, ctx: commands.Context, count: int):
        if not 1 <= count <= 50:
            return await ctx.deny(MESSAGES["invalid_threshold"])
        await self.bot.pool.execute(
            "INSERT INTO starboard_guilds (guild_id, threshold) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET threshold = $2",
            ctx.guild.id, count,
        )
        await ctx.approve(MESSAGES["threshold_set"].format(n=count))

    @starboard.command(
        name="emoji",
        description="Set the trigger emoji.",
    )
    @example(",starboard emoji ⭐")
    async def starboard_emoji(self, ctx: commands.Context, emoji: str):
        await self.bot.pool.execute(
            "INSERT INTO starboard_guilds (guild_id, emoji) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET emoji = $2",
            ctx.guild.id, emoji,
        )
        await ctx.approve(MESSAGES["emoji_set"].format(emoji=emoji))

    @starboard.command(
        name="ignore",
        description="Ignore a channel.",
    )
    @example(",starboard ignore #memes")
    async def starboard_ignore(self, ctx: commands.Context, channel: discord.TextChannel):
        row = await self.bot.pool.fetchrow(
            "SELECT ignored_channels FROM starboard_guilds WHERE guild_id = $1", ctx.guild.id
        )
        ignored = json.loads(row["ignored_channels"]) if row and row["ignored_channels"] else []
        if channel.id not in ignored:
            ignored.append(channel.id)
            await self.bot.pool.execute(
                "INSERT INTO starboard_guilds (guild_id, ignored_channels) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET ignored_channels = $2",
                ctx.guild.id, json.dumps(ignored),
            )
        await ctx.approve(MESSAGES["ignored"].format(channel=channel.mention))

    @starboard.command(
        name="unignore",
        description="Stop ignoring a channel.",
    )
    @example(",starboard unignore #memes")
    async def starboard_unignore(self, ctx: commands.Context, channel: discord.TextChannel):
        row = await self.bot.pool.fetchrow(
            "SELECT ignored_channels FROM starboard_guilds WHERE guild_id = $1", ctx.guild.id
        )
        ignored = json.loads(row["ignored_channels"]) if row and row["ignored_channels"] else []
        if channel.id in ignored:
            ignored.remove(channel.id)
            await self.bot.pool.execute(
                "INSERT INTO starboard_guilds (guild_id, ignored_channels) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET ignored_channels = $2",
                ctx.guild.id, json.dumps(ignored),
            )
        await ctx.approve(MESSAGES["unignored"].format(channel=channel.mention))

    @starboard.command(
        name="disable",
        description="Disable the starboard.",
    )
    @example(",starboard disable")
    async def starboard_disable(self, ctx: commands.Context):
        await self.bot.pool.execute(
            "INSERT INTO starboard_guilds (guild_id, channel_id) VALUES ($1, 0) ON CONFLICT (guild_id) DO UPDATE SET channel_id = 0",
            ctx.guild.id,
        )
        await ctx.approve(MESSAGES["disabled"])

    @starboard.command(
        name="config",
        description="Show current starboard config.",
    )
    @example(",starboard config")
    async def starboard_config(self, ctx: commands.Context):
        row = await self.bot.pool.fetchrow(
            "SELECT * FROM starboard_guilds WHERE guild_id = $1", ctx.guild.id
        )
        if not row:
            return await ctx.warn(MESSAGES["channel_missing"])

        ch = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        ignored = json.loads(row["ignored_channels"]) if row["ignored_channels"] else []
        ignored_str = ", ".join(f"<#{c}>" for c in ignored) or "—"

        embed = discord.Embed(
            title=f"{'⭐'} Starboard Config",
            color=0x747C8C,
        )
        embed.add_field(name="Channel", value=ch.mention if ch else "—", inline=False)
        embed.add_field(name="Threshold", value=f"`{row['threshold']}`", inline=True)
        embed.add_field(name="Emoji", value=row["emoji"], inline=True)
        embed.add_field(name="Ignored Channels", value=ignored_str, inline=False)

        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._on_reaction(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._on_reaction(payload)

    async def _on_reaction(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return

        row = await self.bot.pool.fetchrow(
            "SELECT * FROM starboard_guilds WHERE guild_id = $1", payload.guild_id
        )
        if not row or not row["channel_id"]:
            return

        emoji_str = str(payload.emoji)
        if emoji_str != row["emoji"]:
            return

        ignored = json.loads(row["ignored_channels"]) if row["ignored_channels"] else []
        if payload.channel_id in ignored:
            return
        if payload.channel_id == row["channel_id"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return
        if message.author.bot:
            return

        count = payload.count or 0

        starboard_ch = guild.get_channel(row["channel_id"])
        if not starboard_ch:
            return

        starred_row = await self.bot.pool.fetchrow(
            "SELECT starboard_message_id FROM starred_messages WHERE guild_id = $1 AND message_id = $2",
            payload.guild_id, message.id,
        )
        existing_id = starred_row["starboard_message_id"] if starred_row else None

        if count >= row["threshold"]:
            embed = self._build_starred_embed(message, count, row)
            if existing_id:
                try:
                    m = await starboard_ch.fetch_message(int(existing_id))
                    await m.edit(embed=embed)
                    return
                except Exception:
                    pass
            try:
                sent = await starboard_ch.send(embed=embed)
                await self.bot.pool.execute(
                    "INSERT INTO starred_messages (guild_id, message_id, starboard_message_id) VALUES ($1, $2, $3) ON CONFLICT (guild_id, message_id) DO UPDATE SET starboard_message_id = $3",
                    payload.guild_id, message.id, sent.id,
                )
            except Exception:
                pass
        else:
            if existing_id:
                try:
                    m = await starboard_ch.fetch_message(int(existing_id))
                    await m.delete()
                except Exception:
                    pass
                await self.bot.pool.execute(
                    "DELETE FROM starred_messages WHERE guild_id = $1 AND message_id = $2",
                    payload.guild_id, message.id,
                )

    def _build_starred_embed(self, message: discord.Message, count: int, row: dict) -> discord.Embed:
        header = MESSAGES["starred"].format(
            emoji=row["emoji"],
            count=count,
            channel=message.channel.mention,
        )

        description = f"{header}\n**{message.author.display_name}** · <t:{int(message.created_at.timestamp())}:R>\n"
        if message.content:
            txt = message.content
            if len(txt) > 4000:
                txt = txt[:4000] + "…"
            description += txt + "\n"
        description += f"[Jump to message]({message.jump_url})"

        embed = discord.Embed(description=description, color=0x747C8C)

        for att in message.attachments:
            if (att.content_type or "").startswith("image/") or att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                embed.set_image(url=att.url)
                break

        return embed


async def setup(bot):
    await bot.add_cog(Starboard(bot))
