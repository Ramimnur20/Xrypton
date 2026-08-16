"""
Birthdays — set/list/announce server member birthdays with optional auto role.

Commands (single `birthday` group):
    birthday set <MM-DD>       — set/update your birthday
    birthday remove            — remove your birthday
    birthday show [user]       — show a user's birthday
    birthday today             — list today's birthdays in this server
    birthday upcoming          — list upcoming birthdays (next 30 days)
    birthday channel <channel> — set the announcement channel (admin)
    birthday role <role>       — set the auto-assigned birthday role (admin)
    birthday config            — show server birthday config (admin)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import discord
from discord.ext import commands, tasks

from base.managers.predicates import example
from base.config import EMOJIS

DATE_RE = re.compile(r"^\s*(\d{1,2})[-/](\d{1,2})\s*$")


MESSAGES = {
    "set_ok":         f"{EMOJIS.APPROVE} Your birthday has been set to **{{date}}**.",
    "removed":        f"{EMOJIS.APPROVE} Your birthday has been removed.",
    "invalid_date":   f"{EMOJIS.DENY} Invalid date. Use `MM-DD` format (e.g. `07-23`).",
    "show_self":      f"🎂 Your birthday is **{{date}}**.",
    "show_other":     f"🎂 {{user}}'s birthday is **{{date}}**.",
    "show_none":      f"📭 {{user}} has no birthday set.",
    "today_empty":    f"🎂 No birthdays today.",
    "upcoming_empty": f"📭 No upcoming birthdays in the next 30 days.",
    "channel_set":    f"{EMOJIS.APPROVE} Birthday announcement channel set to **{{channel}}**.",
    "role_set":       f"{EMOJIS.APPROVE} Birthday role set to **{{role}}**.",
    "happy_birthday": "🎂🎉 Happy birthday {mention}! Wishing you a wonderful day! 🎈",
}


def _parse_date(text: str) -> Optional[str]:
    m = DATE_RE.fullmatch(text)
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        datetime(2024, mo, d)
    except ValueError:
        return None
    return f"{mo:02d}-{d:02d}"


def _format_date(s: str) -> str:
    try:
        m, d = s.split("-")
        return datetime(2024, int(m), int(d)).strftime("%B %d")
    except Exception:
        return s


class Birthdays(commands.Cog):
    """Server birthday announcements with optional auto-role."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.pool.execute("""
            CREATE TABLE IF NOT EXISTS birthday_users (
                user_id INTEGER PRIMARY KEY,
                date TEXT
            )
        """)
        await self.bot.pool.execute("""
            CREATE TABLE IF NOT EXISTS birthday_guilds (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER DEFAULT 0,
                role_id INTEGER DEFAULT 0,
                last_run TEXT
            )
        """)
        self.daily_check.start()

    def cog_unload(self):
        self.daily_check.cancel()

    @commands.hybrid_group(
        name="birthday",
        description="Birthday system.",
        invoke_without_command=True,
    )
    @example(",birthday")
    async def birthday(self, ctx: commands.Context):
        await ctx.send_help(self.birthday)

    @birthday.command(
        name="set",
        description="Set your birthday (MM-DD).",
    )
    @example(",birthday set 07-23")
    async def birthday_set(self, ctx: commands.Context, date: str):
        d = _parse_date(date)
        if not d:
            return await ctx.deny(MESSAGES["invalid_date"])
        await self.bot.pool.execute(
            "INSERT INTO birthday_users (user_id, date) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET date = $2",
            ctx.author.id, d,
        )
        await ctx.approve(MESSAGES["set_ok"].format(date=_format_date(d)))

    @birthday.command(
        name="remove",
        description="Remove your birthday.",
    )
    @example(",birthday remove")
    async def birthday_remove(self, ctx: commands.Context):
        await self.bot.pool.execute(
            "DELETE FROM birthday_users WHERE user_id = $1", ctx.author.id,
        )
        await ctx.approve(MESSAGES["removed"])

    @birthday.command(
        name="show",
        description="Show a user's birthday.",
    )
    @example(",birthday show @user")
    async def birthday_show(self, ctx: commands.Context, user: discord.Member = None):
        target = user or ctx.author
        row = await self.bot.pool.fetchrow(
            "SELECT date FROM birthday_users WHERE user_id = $1", target.id,
        )
        if not row:
            return await ctx.warn(MESSAGES["show_none"].format(user=target.mention))
        formatted = _format_date(row["date"])
        if target == ctx.author:
            await ctx.send(MESSAGES["show_self"].format(date=formatted))
        else:
            await ctx.send(MESSAGES["show_other"].format(user=target.mention, date=formatted))

    @birthday.command(
        name="today",
        description="List members with a birthday today.",
    )
    @example(",birthday today")
    async def birthday_today(self, ctx: commands.Context):
        today = datetime.now(timezone.utc).strftime("%m-%d")
        rows = await self.bot.pool.fetch(
            "SELECT user_id FROM birthday_users WHERE date = $1", today,
        )
        results = []
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            if member:
                results.append(f"• {member.mention}")
        if not results:
            return await ctx.warn(MESSAGES["today_empty"])

        embed = discord.Embed(
            title=f"❤  Birthdays Today",
            description="\n".join(results[:50]),
            color=0x747C8C,
        )
        await ctx.send(embed=embed)

    @birthday.command(
        name="upcoming",
        description="Upcoming birthdays in the next 30 days.",
    )
    @example(",birthday upcoming")
    async def birthday_upcoming(self, ctx: commands.Context):
        today = datetime.now(timezone.utc).date()
        rows = await self.bot.pool.fetch("SELECT user_id, date FROM birthday_users")
        entries: List[tuple] = []
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            if not member:
                continue
            d = row["date"]
            try:
                mo, da = (int(x) for x in d.split("-"))
                this_year = today.replace(month=mo, day=da)
            except Exception:
                continue
            target = this_year
            if target < today:
                try:
                    target = target.replace(year=today.year + 1)
                except Exception:
                    pass
            delta = (target - today).days
            if 0 <= delta <= 30:
                entries.append((delta, member.mention, _format_date(d)))
        if not entries:
            return await ctx.warn(MESSAGES["upcoming_empty"])
        entries.sort()
        body = "\n".join(
            f"• **{date}** · {who} · `in {d}d`" for d, who, date in entries[:30]
        )

        embed = discord.Embed(
            title=f"❤ Upcoming Birthdays",
            description=body,
            color=0x747C8C,
        )
        await ctx.send(embed=embed)

    @birthday.command(
        name="channel",
        description="Set the birthday announcement channel.",
    )
    @commands.has_permissions(manage_guild=True)
    @example(",birthday channel #announcements")
    async def birthday_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.bot.pool.execute(
            "INSERT INTO birthday_guilds (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2",
            ctx.guild.id, channel.id,
        )
        await ctx.approve(MESSAGES["channel_set"].format(channel=channel.mention))

    @birthday.command(
        name="role",
        description="Set the auto-assigned birthday role.",
    )
    @commands.has_permissions(manage_guild=True)
    @example(",birthday role @Birthday")
    async def birthday_role(self, ctx: commands.Context, role: discord.Role):
        await self.bot.pool.execute(
            "INSERT INTO birthday_guilds (guild_id, role_id) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET role_id = $2",
            ctx.guild.id, role.id,
        )
        await ctx.approve(MESSAGES["role_set"].format(role=role.mention))

    @birthday.command(
        name="config",
        description="Show server birthday config.",
    )
    @commands.has_permissions(manage_guild=True)
    @example(",birthday config")
    async def birthday_config(self, ctx: commands.Context):
        row = await self.bot.pool.fetchrow(
            "SELECT * FROM birthday_guilds WHERE guild_id = $1", ctx.guild.id,
        )
        if not row:
            ch = rl = None
        else:
            ch = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
            rl = ctx.guild.get_role(row["role_id"]) if row["role_id"] else None

        embed = discord.Embed(
            title=f"♥  Birthday Config",
            color=0x747C8C,
        )
        embed.add_field(name="Channel", value=ch.mention if ch else "—", inline=False)
        embed.add_field(name="Role", value=rl.mention if rl else "—", inline=False)

        await ctx.send(embed=embed)


    @tasks.loop(minutes=15)
    async def daily_check(self):
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        row = await self.bot.pool.fetchrow(
            "SELECT last_run FROM birthday_guilds WHERE guild_id = $1", 0,
        )
        last = row["last_run"] if row else None
        if last == date_str:
            await self._strip_stale_birthday_roles(now)
            return
        if now.hour < 9:
            return

        today = now.strftime("%m-%d")
        rows = await self.bot.pool.fetch(
            "SELECT guild_id, channel_id, role_id FROM birthday_guilds WHERE channel_id != 0 OR role_id != 0"
        )
        for gcfg in rows:
            guild = self.bot.get_guild(gcfg["guild_id"])
            if not guild:
                continue
            ch = guild.get_channel(gcfg["channel_id"]) if gcfg["channel_id"] else None
            role = guild.get_role(gcfg["role_id"]) if gcfg["role_id"] else None
            user_rows = await self.bot.pool.fetch(
                "SELECT user_id FROM birthday_users WHERE date = $1", today,
            )
            for urow in user_rows:
                member = guild.get_member(urow["user_id"])
                if not member:
                    continue
                if ch:
                    try:
                        await ch.send(MESSAGES["happy_birthday"].format(mention=member.mention))
                    except Exception:
                        pass
                if role:
                    try:
                        await member.add_roles(role, reason="Birthday")
                    except Exception:
                        pass
        await self.bot.pool.execute(
            "INSERT INTO birthday_guilds (guild_id, last_run) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET last_run = $2",
            0, date_str,
        )
        await self._strip_stale_birthday_roles(now)

    async def _strip_stale_birthday_roles(self, now: datetime):
        today = now.strftime("%m-%d")
        rows = await self.bot.pool.fetch(
            "SELECT guild_id, role_id FROM birthday_guilds WHERE role_id != 0"
        )
        for gcfg in rows:
            guild = self.bot.get_guild(gcfg["guild_id"])
            if not guild:
                continue
            role = guild.get_role(gcfg["role_id"])
            if not role:
                continue
            for member in role.members:
                row = await self.bot.pool.fetchrow(
                    "SELECT date FROM birthday_users WHERE user_id = $1", member.id,
                )
                if not row or row["date"] != today:
                    try:
                        await member.remove_roles(role, reason="Birthday over")
                    except Exception:
                        pass

    @daily_check.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Birthdays(bot))
