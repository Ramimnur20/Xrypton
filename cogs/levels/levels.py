import math
import random
import io
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord.ext.commands import Cog, hybrid_group, hybrid_command
from PIL import Image, ImageDraw

from base.context import Context
from base.config import *


async def create_progress_bar(xp, level):
    def _create_bar():
        xp_end = math.floor(5 * math.sqrt(level) + 50 * level + 30)
        percentage = (xp / xp_end) if xp_end > 0 else 0

        width, height = 400, 30
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=15, fill=(60, 60, 60, 255))

        if percentage > 0:
            progress_width = int((width - 4) * percentage)
            if progress_width > 0:
                draw.rounded_rectangle([2, 2, progress_width + 2, height - 3], radius=13, fill=(128, 164, 168, 255))

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_create_bar)


def render_template(template: str, message: discord.Message, new_level: int, xp: int, total_xp: int) -> str:
    """Simple placeholder-based level-up message templating (no external scripting engine)."""
    try:
        return template.format(
            user=message.author.mention,
            username=message.author.name,
            guild=message.guild.name,
            level=new_level,
            xp=xp,
            total_xp=total_xp,
        )
    except Exception:
        return f"🎉 {message.author.mention} leveled up to **level {new_level}**!"


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # These tables aren't in schema.sql, so we create them here to keep this cog fully drop-in.
        # Postgres schema-qualified names (level.config etc.) don't translate to SQLite, so they're
        # flattened to level_config / level_member / level_role / level_notification.
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS level_config (
                guild_id INTEGER PRIMARY KEY,
                status INTEGER DEFAULT 1,
                cooldown INTEGER DEFAULT 60,
                xp_multiplier REAL DEFAULT 1.0,
                xp_min INTEGER DEFAULT 15,
                xp_max INTEGER DEFAULT 25,
                max_level INTEGER DEFAULT 0,
                stack_roles INTEGER DEFAULT 0,
                effort_status INTEGER DEFAULT 0,
                effort_text INTEGER DEFAULT 50,
                effort_image INTEGER DEFAULT 0,
                effort_booster INTEGER DEFAULT 0
            )
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS level_member (
                guild_id INTEGER,
                user_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                total_xp INTEGER DEFAULT 0,
                last_message TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS level_role (
                guild_id INTEGER,
                role_id INTEGER,
                level INTEGER,
                PRIMARY KEY (guild_id, level)
            )
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS level_notification (
                guild_id INTEGER PRIMARY KEY,
                dm INTEGER DEFAULT 0,
                channel_id INTEGER,
                template TEXT
            )
            """
        )

    @hybrid_command()
    async def rank(self, ctx: Context, member: discord.Member = None):
        if member is None:
            member = ctx.author

        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config or not config["status"]:
            return await ctx.warn("Levels **aren't** enabled in this server.")

        member_data = await self.bot.pool.fetchrow(
            "SELECT * FROM level_member WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, member.id
        )

        if not member_data:
            level, xp = 0, 0
        else:
            level = member_data["level"]
            xp = member_data["xp"]

        xp_end = math.floor(5 * math.sqrt(level) + 50 * level + 30)
        percentage = int(xp / xp_end * 100) if xp_end > 0 else 0

        progress_bar = await create_progress_bar(xp, level)
        file = discord.File(progress_bar, filename="progress.png")

        embed = discord.Embed(
            color=COLORS.neutral,
            title=f"{member.name}'s rank"
        ).set_author(
            name=str(member), icon_url=member.display_avatar.url
        ).add_field(
            name="XP", value=f"**{xp:,}** / **{xp_end:,}**"
        ).add_field(
            name="Level", value=f"**{level}**"
        ).add_field(
            name="Progress", value=f"**{percentage}%**"
        ).set_image(url="attachment://progress.png")

        await ctx.send(embed=embed, file=file)

    @hybrid_group(invoke_without_command=True)
    async def level(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @level.group(invoke_without_command=True)
    async def rewards(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @rewards.command()
    @commands.has_permissions(manage_guild=True)
    async def add(self, ctx: Context, level: int, *, role: discord.Role):
        if role.permissions.administrator or role.permissions.manage_guild:
            return await ctx.warn("You **cannot** make a level role a role with dangerous permissions.")

        existing = await self.bot.pool.fetchrow(
            "SELECT * FROM level_role WHERE guild_id = $1 AND level = $2",
            ctx.guild.id, level
        )
        if existing:
            return await ctx.warn(f"A role has been **already** assigned for level **{level}**.")

        await self.bot.pool.execute(
            "INSERT INTO level_role (guild_id, role_id, level) VALUES ($1, $2, $3)",
            ctx.guild.id, role.id, level
        )
        await ctx.approve(f"I have **added** {role.mention} for level **{level}** reward.")

    @rewards.command()
    @commands.has_permissions(manage_guild=True)
    async def remove(self, ctx: Context, level: int):
        existing = await self.bot.pool.fetchrow(
            "SELECT * FROM level_role WHERE guild_id = $1 AND level = $2",
            ctx.guild.id, level
        )
        if not existing:
            return await ctx.warn(f"There is **no** role assigned for level **{level}**.")

        await self.bot.pool.execute(
            "DELETE FROM level_role WHERE guild_id = $1 AND level = $2",
            ctx.guild.id, level
        )
        await ctx.approve(f"I have **removed** level **{level}** reward.")

    @rewards.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def rewards_reset(self, ctx: Context):
        results = await self.bot.pool.fetch(
            "SELECT * FROM level_role WHERE guild_id = $1", ctx.guild.id
        )
        if not results:
            return await ctx.warn("There are **no** role rewards in this server.")

        await self.bot.pool.execute(
            "DELETE FROM level_role WHERE guild_id = $1", ctx.guild.id
        )
        await ctx.approve("I have reset **all** level rewards.")

    @rewards.command(name="list")
    async def rewards_list(self, ctx: Context):
        results = await self.bot.pool.fetch(
            "SELECT * FROM level_role WHERE guild_id = $1 ORDER BY level",
            ctx.guild.id
        )
        if not results:
            return await ctx.warn("There are **no** role rewards in this server.")

        description = ""
        for i, row in enumerate(results[:10], 1):
            role = ctx.guild.get_role(row["role_id"])
            role_mention = role.mention if role else f"<@&{row['role_id']}>"
            description += f"\n`{i}` level **{row['level']}** - {role_mention}"

        embed = discord.Embed(
            color=COLORS.neutral,
            description=description
        ).set_author(
            name="Level Rewards",
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )

        await ctx.send(embed=embed)

    @level.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def level_reset(self, ctx: Context, *, member: discord.Member = None):
        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("Levels are not configured.")

        if not member:
            await self.bot.pool.execute(
                "DELETE FROM level_member WHERE guild_id = $1", ctx.guild.id
            )
            await ctx.approve("I have reset levels for **all** members.")
        else:
            await self.bot.pool.execute(
                "DELETE FROM level_member WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id, member.id
            )
            await ctx.approve(f"I have reset levels for **{member}**.")

    @level.command(aliases=["lb"])
    async def leaderboard(self, ctx: Context):
        results = await self.bot.pool.fetch(
            "SELECT * FROM level_member WHERE guild_id = $1 ORDER BY total_xp DESC LIMIT 10",
            ctx.guild.id
        )
        if not results:
            return await ctx.warn("Nobody is on the **level leaderboard**")

        description = ""
        for i, row in enumerate(results, 1):
            user = self.bot.get_user(row["user_id"]) or f"<@{row['user_id']}>"
            crown = "🏆" if i == 1 else f"`{i}`"
            description += f"\n{crown} **{user}** - **{row['xp']}** xp (level {row['level']})"

        embed = discord.Embed(
            color=COLORS.neutral,
            description=description
        ).set_author(
            name="Level Leaderboard",
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )

        await ctx.send(embed=embed)

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def toggle(self, ctx: Context):
        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )

        if not config:
            await self.bot.pool.execute(
                "INSERT INTO level_config (guild_id) VALUES ($1)", ctx.guild.id
            )
            await ctx.approve("I have **enabled** the leveling system.")
        else:
            new_status = not config["status"]
            await self.bot.pool.execute(
                "UPDATE level_config SET status = $1 WHERE guild_id = $2",
                int(new_status), ctx.guild.id
            )
            status_text = "enabled" if new_status else "disabled"
            await ctx.approve(f"I have **{status_text}** the leveling system.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def levelup(self, ctx: Context, destination: str):
        if destination not in ["dms", "channel", "off"]:
            return await ctx.warn("You passed an **invalid** destination.")

        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("The leveling system is **not** enabled.")

        dm_setting = destination == "dms"
        await self.bot.pool.execute(
            "INSERT INTO level_notification (guild_id, dm) VALUES ($1, $2) "
            "ON CONFLICT (guild_id) DO UPDATE SET dm = excluded.dm",
            ctx.guild.id, int(dm_setting)
        )

        await ctx.approve(f"I have **updated** the level up message destination: **{destination}**.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def message(self, ctx: Context, *, template: str = None):
        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("The leveling system is **not** enabled.")

        if not template:
            await self.bot.pool.execute(
                "UPDATE level_notification SET template = NULL WHERE guild_id = $1",
                ctx.guild.id
            )
            await ctx.approve("Reset level up message to default.")
        else:
            await self.bot.pool.execute(
                "INSERT INTO level_notification (guild_id, template) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET template = excluded.template",
                ctx.guild.id, template
            )
            await ctx.approve(
                "Set custom level up message. Use `{user}`, `{level}`, `{xp}`, `{total_xp}`, or `{guild}` as placeholders."
            )

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def channel(self, ctx: Context, *, channel: discord.TextChannel = None):
        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("The leveling system is **not** enabled.")

        if not channel:
            await self.bot.pool.execute(
                "UPDATE level_notification SET channel_id = NULL WHERE guild_id = $1",
                ctx.guild.id
            )
            await ctx.approve("I have **removed** the channel for level up messages.")
        else:
            await self.bot.pool.execute(
                "INSERT INTO level_notification (guild_id, channel_id) VALUES ($1, $2) "
                "ON CONFLICT (guild_id) DO UPDATE SET channel_id = excluded.channel_id",
                ctx.guild.id, channel.id
            )
            await ctx.approve(f"I have set the channel for level up messages to {channel.mention}.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def cooldown(self, ctx: Context, seconds: int):
        if seconds < 0 or seconds > 3600:
            return await ctx.warn("Cooldown must be between **0** and **3600** seconds.")

        await self.bot.pool.execute(
            "UPDATE level_config SET cooldown = $1 WHERE guild_id = $2",
            seconds, ctx.guild.id
        )
        await ctx.approve(f"Set XP cooldown to **{seconds}** seconds.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def multiplier(self, ctx: Context, multiplier: float):
        if multiplier < 0.1 or multiplier > 10:
            return await ctx.warn("Multiplier must be between **0.1** and **10**.")

        await self.bot.pool.execute(
            "UPDATE level_config SET xp_multiplier = $1 WHERE guild_id = $2",
            multiplier, ctx.guild.id
        )
        await ctx.approve(f"Set XP multiplier to **{multiplier}x**.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def xprange(self, ctx: Context, min_xp: int, max_xp: int):
        if min_xp < 1 or max_xp < min_xp or max_xp > 100:
            return await ctx.warn("Invalid XP range. Min must be ≥1, max must be ≥min and ≤100.")

        await self.bot.pool.execute(
            "UPDATE level_config SET xp_min = $1, xp_max = $2 WHERE guild_id = $3",
            min_xp, max_xp, ctx.guild.id
        )
        await ctx.approve(f"Set XP range to **{min_xp}-{max_xp}** per message.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def maxlevel(self, ctx: Context, max_level: int = None):
        if max_level is not None and max_level < 1:
            return await ctx.warn("Max level must be at least **1** or **0** to disable.")

        await self.bot.pool.execute(
            "UPDATE level_config SET max_level = $1 WHERE guild_id = $2",
            max_level or 0, ctx.guild.id
        )

        if max_level:
            await ctx.approve(f"Set max level to **{max_level}**.")
        else:
            await ctx.approve("Removed max level limit.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def stackroles(self, ctx: Context):
        config = await self.bot.pool.fetchrow(
            "SELECT stack_roles FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("Levels are not configured.")

        new_setting = not config["stack_roles"]
        await self.bot.pool.execute(
            "UPDATE level_config SET stack_roles = $1 WHERE guild_id = $2",
            int(new_setting), ctx.guild.id
        )

        status = "enabled" if new_setting else "disabled"
        await ctx.approve(f"Role stacking has been **{status}**.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def effort(self, ctx: Context, toggle: str = None):
        if toggle and toggle.lower() not in ["on", "off"]:
            return await ctx.warn("Use **on** or **off** to toggle effort rewards.")

        config = await self.bot.pool.fetchrow(
            "SELECT effort_status FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("Levels are not configured.")

        if toggle:
            new_setting = toggle.lower() == "on"
            await self.bot.pool.execute(
                "UPDATE level_config SET effort_status = $1 WHERE guild_id = $2",
                int(new_setting), ctx.guild.id
            )
            status = "enabled" if new_setting else "disabled"
            await ctx.approve(f"Effort rewards have been **{status}**.")
        else:
            status = "enabled" if config["effort_status"] else "disabled"
            await ctx.embed(description=f"Effort rewards are currently **{status}**.", color=COLORS.neutral)

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def efforttext(self, ctx: Context, characters: int):
        if characters < 10 or characters > 500:
            return await ctx.warn("Text effort threshold must be between **10** and **500** characters.")

        await self.bot.pool.execute(
            "UPDATE level_config SET effort_text = $1 WHERE guild_id = $2",
            characters, ctx.guild.id
        )
        await ctx.approve(f"Set text effort threshold to **{characters}** characters.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def effortimage(self, ctx: Context, bonus_xp: int):
        if bonus_xp < 0 or bonus_xp > 50:
            return await ctx.warn("Image effort bonus must be between **0** and **50** XP.")

        await self.bot.pool.execute(
            "UPDATE level_config SET effort_image = $1 WHERE guild_id = $2",
            bonus_xp, ctx.guild.id
        )
        await ctx.approve(f"Set image effort bonus to **{bonus_xp}** XP.")

    @level.command()
    @commands.has_permissions(manage_guild=True)
    async def boosterbonus(self, ctx: Context, bonus_xp: int):
        if bonus_xp < 0 or bonus_xp > 100:
            return await ctx.warn("Booster bonus must be between **0** and **100** XP.")

        await self.bot.pool.execute(
            "UPDATE level_config SET effort_booster = $1 WHERE guild_id = $2",
            bonus_xp, ctx.guild.id
        )
        await ctx.approve(f"Set booster bonus to **{bonus_xp}** XP.")

    @level.command()
    async def config(self, ctx: Context):
        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id
        )
        if not config:
            return await ctx.warn("Levels are not configured.")

        embed = discord.Embed(
            title="Level Configuration",
            color=COLORS.neutral
        )

        embed.add_field(name="Status", value="Enabled" if config["status"] else "Disabled")
        embed.add_field(name="Cooldown", value=f"{config['cooldown']}s")
        embed.add_field(name="XP Range", value=f"{config['xp_min']}-{config['xp_max']}")
        embed.add_field(name="XP Multiplier", value=f"{config['xp_multiplier']}x")
        embed.add_field(name="Max Level", value=config["max_level"] or "None")
        embed.add_field(name="Stack Roles", value="Yes" if config["stack_roles"] else "No")
        embed.add_field(name="Effort Rewards", value="Enabled" if config["effort_status"] else "Disabled")
        embed.add_field(name="Text Threshold", value=f"{config['effort_text']} chars")
        embed.add_field(name="Image Bonus", value=f"{config['effort_image']} XP")
        embed.add_field(name="Booster Bonus", value=f"{config['effort_booster']} XP")

        notification = await self.bot.pool.fetchrow(
            "SELECT * FROM level_notification WHERE guild_id = $1", ctx.guild.id
        )
        if notification:
            embed.add_field(name="Level Up DMs", value="Yes" if notification["dm"] else "No")
            embed.add_field(
                name="Level Up Channel",
                value=f"<#{notification['channel_id']}>" if notification["channel_id"] else "Current"
            )
            embed.add_field(name="Custom Message", value="Yes" if notification["template"] else "Default")

        await ctx.send(embed=embed)


class LevelEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", message.guild.id
        )
        if not config or not config["status"]:
            return

        member_data = await self.bot.pool.fetchrow(
            "SELECT * FROM level_member WHERE guild_id = $1 AND user_id = $2",
            message.guild.id, message.author.id
        )

        now = datetime.now(timezone.utc)

        if member_data and member_data["last_message"]:
            last_message = datetime.fromisoformat(member_data["last_message"])
            time_diff = (now - last_message).total_seconds()
            if time_diff < config["cooldown"]:
                return

        xp_gain = random.randint(config["xp_min"], config["xp_max"])

        if config["effort_status"]:
            if len(message.content) >= config["effort_text"]:
                xp_gain += 5
            if message.attachments:
                xp_gain += config["effort_image"]
            if message.author.premium_since:
                xp_gain += config["effort_booster"]

        xp_gain = int(xp_gain * config["xp_multiplier"])

        if not member_data:
            await self.bot.pool.execute(
                "INSERT INTO level_member (guild_id, user_id, xp, level, total_xp, last_message) VALUES ($1, $2, $3, $4, $5, $6)",
                message.guild.id, message.author.id, xp_gain, 0, xp_gain, now.isoformat()
            )
            current_xp = xp_gain
            current_level = 0
        else:
            current_xp = member_data["xp"] + xp_gain
            current_level = member_data["level"]
            total_xp = member_data["total_xp"] + xp_gain

            await self.bot.pool.execute(
                "UPDATE level_member SET xp = $1, total_xp = $2, last_message = $3 WHERE guild_id = $4 AND user_id = $5",
                current_xp, total_xp, now.isoformat(), message.guild.id, message.author.id
            )

        xp_needed = math.floor(5 * math.sqrt(current_level + 1) + 50 * (current_level + 1) + 30)

        if current_xp >= xp_needed and (not config["max_level"] or current_level < config["max_level"]):
            new_level = current_level + 1
            new_xp = current_xp - xp_needed

            await self.bot.pool.execute(
                "UPDATE level_member SET level = $1, xp = $2 WHERE guild_id = $3 AND user_id = $4",
                new_level, new_xp, message.guild.id, message.author.id
            )

            await self.handle_level_up(message, new_level)

    async def handle_level_up(self, message: discord.Message, new_level: int):
        notification = await self.bot.pool.fetchrow(
            "SELECT * FROM level_notification WHERE guild_id = $1", message.guild.id
        )

        level_roles = await self.bot.pool.fetch(
            "SELECT * FROM level_role WHERE guild_id = $1 AND level <= $2",
            message.guild.id, new_level
        )

        config = await self.bot.pool.fetchrow(
            "SELECT * FROM level_config WHERE guild_id = $1", message.guild.id
        )

        if level_roles:
            member = message.author
            if config["stack_roles"]:
                roles_to_add = [message.guild.get_role(row["role_id"]) for row in level_roles]
                roles_to_add = [role for role in roles_to_add if role and role not in member.roles]
                if roles_to_add:
                    try:
                        await member.add_roles(*roles_to_add, reason=f"Level {new_level} reward")
                    except Exception:
                        pass
            else:
                highest_role_data = max(level_roles, key=lambda x: x["level"])
                highest_role = message.guild.get_role(highest_role_data["role_id"])
                if highest_role and highest_role not in member.roles:
                    current_level_roles = [
                        message.guild.get_role(row["role_id"])
                        for row in level_roles
                        if message.guild.get_role(row["role_id"]) in member.roles
                    ]
                    try:
                        if current_level_roles:
                            await member.remove_roles(*current_level_roles, reason="Level role update")
                        await member.add_roles(highest_role, reason=f"Level {new_level} reward")
                    except Exception:
                        pass

        if not notification:
            return

        level_up_message = f"🎉 {message.author.mention} leveled up to **level {new_level}**!"

        if notification["template"]:
            member_data = await self.bot.pool.fetchrow(
                "SELECT * FROM level_member WHERE guild_id = $1 AND user_id = $2",
                message.guild.id, message.author.id
            )
            level_up_message = render_template(
                notification["template"],
                message,
                new_level,
                member_data["xp"] if member_data else 0,
                member_data["total_xp"] if member_data else 0,
            )

        if notification["dm"]:
            try:
                await message.author.send(level_up_message)
            except Exception:
                pass
        elif notification["channel_id"]:
            channel = message.guild.get_channel(notification["channel_id"])
            if channel:
                try:
                    await channel.send(level_up_message)
                except Exception:
                    pass
        else:
            try:
                await message.channel.send(level_up_message)
            except Exception:
                pass