from collections import defaultdict
from asyncio import Lock
from random import sample
from datetime import datetime, timedelta

import discord
from discord import Embed, Message, RawReactionActionEvent, TextChannel, utils
from discord.ext import tasks
from discord.ext.commands import BadArgument, Cog, hybrid_group, has_permissions

from humanfriendly import parse_timespan

from base.context import Context
from base.managers.types import CogMeta
from base.config import *


class Giveaway(CogMeta):
    def __init__(self, bot):
        self.bot = bot

    @hybrid_group(name="giveaway", aliases=["gw"], invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def giveaway(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @giveaway.command(name="start")
    @has_permissions(manage_channels=True)
    async def giveaway_start(
        self,
        ctx: Context,
        channel: TextChannel,
        duration: str,
        winners: int,
        *,
        prize: str,
    ):
        try:
            end_time = datetime.now() + timedelta(seconds=parse_timespan(duration))
        except Exception:
            return await ctx.warn("Invalid duration format.")

        embed = Embed(
            title=prize,
            description=(
                f"React with 🎉 to enter the giveaway.\n"
                f"**Ends:** {utils.format_dt(end_time, style='R')} "
                f"({utils.format_dt(end_time, style='F')})\n"
                f"**Winners:** {winners}\n"
                f"**Hosted by:** {ctx.author.mention}"
            ),
            color=COLORS.neutral,
            timestamp=datetime.now(),
        )

        message = await channel.send(embed=embed)
        await message.add_reaction("🎉")

        await self.bot.pool.execute(
            "INSERT INTO giveaway (guild_id, user_id, channel_id, message_id, prize, emoji, winners, ends_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            ctx.guild.id,
            ctx.author.id,
            channel.id,
            message.id,
            prize,
            "🎉",
            winners,
            end_time,
        )
        return await ctx.message.add_reaction("👍")

    @giveaway.command(name="end")
    @has_permissions(manage_channels=True)
    async def giveaway_end(self, ctx: Context, message: Message):
        giveaway = await self.bot.pool.fetchrow(
            "SELECT * FROM giveaway WHERE message_id = $1", message.id
        )
        if not giveaway:
            return await ctx.warn("That is not a giveaway.")

        self.bot.dispatch("giveaway_end", ctx.guild, message.channel, giveaway)
        return await ctx.message.add_reaction("👍")

    @giveaway.command(name="reroll")
    @has_permissions(manage_channels=True)
    async def giveaway_reroll(self, ctx: Context, message: Message, winners: int = 1):
        giveaway = await self.bot.pool.fetchrow(
            "SELECT * FROM giveaway WHERE message_id = $1", message.id
        )
        if not giveaway:
            return await ctx.warn("That is not a giveaway.")

        entries = await self.bot.pool.fetch(
            "SELECT user_id FROM giveaway_entries WHERE message_id = $1", message.id
        )
        valid_entries = [
            ctx.guild.get_member(entry["user_id"])
            for entry in entries
            if ctx.guild.get_member(entry["user_id"])
        ]

        if not valid_entries:
            return await ctx.warn("No valid entries found.")

        if len(valid_entries) < winners:
            new_winners = valid_entries
        else:
            new_winners = sample(valid_entries, winners)

        winners_string = ", ".join(m.mention for m in new_winners)
        embed = Embed(
            title=f"Winners for {giveaway['prize']}",
            description=(
                f"{winners_string} "
                f"{'have' if len(new_winners) > 1 else 'has'} won the giveaway hosted by <@{giveaway['user_id']}>"
            ),
            color=COLORS.neutral,
            timestamp=datetime.now(),
        )
        await ctx.reply(embed=embed)
        return await ctx.message.add_reaction("👍")

    @giveaway.command(name="cancel")
    @has_permissions(manage_channels=True)
    async def giveaway_cancel(self, ctx: Context, message: Message):
        await self.bot.pool.execute(
            "DELETE FROM giveaway WHERE message_id = $1", message.id
        )
        try:
            await message.delete()
        except Exception:
            pass
        return await ctx.approve("Successfully cancelled that giveaway.")

    @giveaway.command(name="list")
    @has_permissions(manage_channels=True)
    async def giveaway_list(self, ctx: Context):
        giveaways = await self.bot.pool.fetch(
            "SELECT * FROM giveaway WHERE guild_id = $1 AND ended = false", ctx.guild.id
        )
        if not giveaways:
            return await ctx.warn("There are no active giveaways in this server.")

        entries = []
        for i, giveaway in enumerate(giveaways, 1):
            link = f"https://discord.com/channels/{giveaway['guild_id']}/{giveaway['channel_id']}/{giveaway['message_id']}"
            entries.append(
                f"`{i}` [**{giveaway['prize']}**]({link}) • Ends {utils.format_dt(giveaway['ends_at'], style='R')}"
            )

        per_page = 5
        embeds = []
        total_pages = (len(entries) + per_page - 1) // per_page

        for page_index in range(total_pages):
            page_entries = entries[
                page_index * per_page : page_index * per_page + per_page
            ]
            embed = Embed(
                title="Active Giveaways",
                description="\n".join(page_entries),
                color=COLORS.neutral,
            )
            embed.set_footer(text=f"Page {page_index + 1}/{total_pages}")
            embeds.append(embed)

        await ctx.paginate(embeds)

    async def cog_command_error(self, ctx: Context, error):
        error = getattr(error, "original", error)
        if isinstance(error, BadArgument):
            message = str(error)
            if "winners" in message:
                return await ctx.warn(
                    "`winners` must be a whole number. Example: `,giveaway start #channel 1h 3 Prize`"
                )
        raise error


class GiveawayEvents(CogMeta):
    def __init__(self, bot):
        self.bot = bot
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

    @Cog.listener("on_giveaway_end")
    async def giveaway_ended(self, guild, channel, giveaway):
        try:
            message = await channel.fetch_message(giveaway["message_id"])
        except Exception:
            message = None

        entries = await self.bot.pool.fetch(
            "SELECT user_id FROM giveaway_entries WHERE message_id = $1",
            giveaway["message_id"],
        )
        valid_entries = [
            guild.get_member(entry["user_id"])
            for entry in entries
            if guild.get_member(entry["user_id"])
        ]

        if not valid_entries:
            embed = Embed(
                title="🎉 Giveaway Ended",
                description="No entries for this giveaway.",
                color=COLORS.neutral,
                timestamp=datetime.now(),
            )
            if message:
                await message.edit(embed=embed)
            else:
                await channel.send(embed=embed)

            await self.bot.pool.execute(
                "UPDATE giveaway SET ended = true WHERE message_id = $1",
                giveaway["message_id"],
            )
            return

        if len(valid_entries) < giveaway["winners"]:
            winners = valid_entries
        else:
            winners = sample(valid_entries, giveaway["winners"])

        winners_string = ", ".join(m.mention for m in winners)
        embed = Embed(
            title="🎉 Giveaway Ended",
            description=f"Won by: {winners_string}",
            color=COLORS.neutral,
            timestamp=datetime.now(),
        )

        if message:
            await message.edit(embed=embed)
        else:
            await channel.send(embed=embed)

        await self.bot.pool.execute(
            "UPDATE giveaway SET ended = true WHERE message_id = $1",
            giveaway["message_id"],
        )

    @Cog.listener("on_raw_reaction_add")
    async def on_giveaway_enter(self, payload: RawReactionActionEvent):
        if str(payload.emoji) != "🎉":
            return

        if not (guild := self.bot.get_guild(payload.guild_id)):
            return
        if not (member := guild.get_member(payload.user_id)):
            return
        if member.bot:
            return

        giveaway = await self.bot.pool.fetchrow(
            "SELECT * FROM giveaway WHERE message_id = $1 AND ended = false",
            payload.message_id,
        )
        if not giveaway:
            return

        existing = await self.bot.pool.fetchrow(
            "SELECT * FROM giveaway_entries WHERE message_id = $1 AND user_id = $2",
            payload.message_id,
            member.id,
        )
        if existing:
            return

        await self.bot.pool.execute(
            "INSERT INTO giveaway_entries (message_id, user_id) VALUES ($1, $2)",
            payload.message_id,
            member.id,
        )

    @Cog.listener("on_raw_reaction_remove")
    async def on_giveaway_leave(self, payload: RawReactionActionEvent):
        if str(payload.emoji) != "🎉":
            return

        if not (guild := self.bot.get_guild(payload.guild_id)):
            return
        if not (member := guild.get_member(payload.user_id)):
            return
        if member.bot:
            return

        await self.bot.pool.execute(
            "DELETE FROM giveaway_entries WHERE message_id = $1 AND user_id = $2",
            payload.message_id,
            member.id,
        )