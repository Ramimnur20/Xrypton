from typing import Union
import requests
import io
import time
import aiohttp
import re

from discord.ext.commands import Cog, Command, Group, command

from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice
from humanize import naturaltime
import humanize
from datetime import datetime
import time

from discord import (
    Embed,
    User,
    Member,
    Message,
    Spotify,
    ActivityType,
    Permissions,
    Status,
    Invite,
    Role,
    Button,
    ButtonStyle,
    PartialEmoji,
    Emoji,
)
from discord.app_commands import (
    allowed_installs,
    allowed_contexts,
)
from discord.ext.commands import (
    command,
    cooldown,
    BucketType,
    Author,
    command,
    hybrid_group,
    group,
    Cog,
)
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url

from psutil import Process
from difflib import get_close_matches
from base.managers.predicates import has_permissions

from PIL import Image
from colorthief import ColorThief


class Information(CogMeta):
    process: Process

    @command(
        name="inviteinfo",
        aliases=["ii"],
        description="Get information about a guild using their invite code.",
    )
    async def inviteinfo(self, ctx: Context, *, invite: Invite = None) -> None:  # type: ignore
        if invite is None:
            return await ctx.warn(f"An `invite code` is missing.")

        return await ctx.embed(
            title=f"Invite code: {invite.code}",
            author={"name": ctx.author.name, "icon_url": ctx.author.display_avatar.url},
            thumbnail=(
                invite.guild.icon.url if invite.guild.icon else "https://none.none"
            ),  # type: ignore
            fields=[
                {
                    "name": "Channel & Invite",
                    "value": f"**Name:** {invite.channel.name} (`text`) \n**ID:** `{invite.channel.id}` \n**Created**: {format_dt(invite.created_at, 'F') if invite.created_at else 'Unkown'} ({format_dt(invite.created_at, 'R') if invite.created_at else ''}) \n**Invite Expiration:** {format_dt(invite.expires_at) if invite.expires_at else 'Never'} \n**Inviter:** {invite.inviter if invite.inviter else 'Vanity URL'} \n **Temporary:** {invite.temporary if invite.temporary else 'N/A'} \n**Usage:** {invite.uses}",  # type: ignore
                    "inline": True,
                },
                {
                    "name": "Guild",
                    "value": f"**Name:** {invite.guild.name} \n**ID:** `{invite.guild.id}` \n**Created:** {format_dt(invite.guild.created_at, 'F')} ({format_dt(invite.guild.created_at, 'R')}) \n**Members:** {invite.approximate_member_count: ,} \n**Online Members:** {invite.approximate_presence_count: ,} \n**Verification Level:** {invite.guild.verification_level}",  # type: ignore
                    "inline": True,
                },
            ],
            buttons=[
                {
                    "label": "Icon",
                    "emoji": "🖼️",
                    "url": (
                        invite.guild.icon.url
                        if invite.guild.icon
                        else "https://none.none"
                    ),  # type: ignore
                },
                {
                    "label": "Splash",
                    "emoji": "🎨",
                    "url": (
                        invite.guild.splash.url
                        if invite.guild.splash
                        else "https://none.none"
                    ),  # type: ignore
                },
                {
                    "label": "Banner",
                    "emoji": "🏳️",
                    "url": (
                        invite.guild.banner.url
                        if invite.guild.banner
                        else "https://none.none"
                    ),  # type: ignore
                },
            ],
        )

    @command(
        name="userinfo",
        aliases=["ui", "whois"],
        description="Get information about a user.",
    )
    async def userinfo(
        self, ctx: Context, *, user: Union[User, Member, str] = None
    ) -> Message:
        if user is None:
            user = ctx.author
        if isinstance(user, (User, Member)):
            member = ctx.guild.get_member(user.id) if ctx.guild else None
        else:
            if user:
                members = ctx.guild.members  # type: ignore
                member_names = [m.display_name for m in members]
                match = get_close_matches(
                    user.lower(),
                    [name.lower() for name in member_names],
                    n=1,
                    cutoff=0.5,
                )
                if match:
                    member = next(
                        m for m in members if m.display_name.lower() == match[0]
                    )
                else:
                    return await ctx.warn(f"No matching user found for `{user}`.")
                user = member
            else:
                user = ctx.author
                member = ctx.guild.get_member(user.id) if ctx.guild else None

        if not user:
            return await ctx.warn("No user found or matched.")

        emojis = []

        if user.public_flags.active_developer:
            emojis.append(EMOJIS.ACTIVE_DEVELOPER)
        elif user.public_flags.bug_hunter:
            emojis.append(EMOJIS.BUG_HUNTER)
        elif user.public_flags.early_supporter:
            emojis.append(EMOJIS.EARLY_SUPPORTER)
        elif user.public_flags.hypesquad_balance:
            emojis.append(EMOJIS.HYPESQUAD_BALANCE)
        elif user.public_flags.hypesquad_bravery:
            emojis.append(EMOJIS.HYPESQUAD_BRAVERY)
        elif user.public_flags.hypesquad_brilliance:
            emojis.append(EMOJIS.HYPESQUAD_BRILLIANCE)
        elif user.public_flags.partner:
            emojis.append(EMOJIS.PARTNER)
        elif user.public_flags.staff:
            emojis.append(EMOJIS.STAFF)
        if not emojis:
            emojis = []

        if isinstance(user, Member):
            if user.activities:
                for activity in user.activities:
                    if isinstance(activity, discord.Spotify):
                        emojis.append(
                            f"\n {EMOJIS.SPOTIFY} Listening to **[{activity.title}]({activity.track_url})** by **`{activity.artists[0]}`**"
                        )

        emoji_string = "".join(emojis) if emojis else ""

        fields = [
            {
                "name": "Dates",
                "value": (
                    f"**Created:** {format_dt(user.created_at, 'd')}{format_dt(user.created_at, 't')} ({format_dt(user.created_at, 'R')})"
                    + (
                        f"\n**Joined:** {format_dt(member.joined_at, 'd')}{format_dt(member.joined_at, 't')} ({format_dt(member.joined_at, 'R')})"
                        if member and member.joined_at
                        else ""
                    )
                ),
            }
        ]

        footer = f"{len(user.mutual_guilds)} mutual guild(s)"
        if member:
            roles = [role.mention for role in member.roles if role.id != ctx.guild.id]  # type: ignore
            role_list = ", ".join(roles) if roles else "None"
            fields.append({"name": f"Roles ({len(roles)})", "value": role_list})

            members = sorted(ctx.guild.members, key=lambda m: m.joined_at)  # type: ignore
            position = members.index(member) + 1
            footer += f" • join position: {position}"

        return await ctx.embed(
            author={"name": f"{user.name} ({user.id})"},
            description=f"{emoji_string}",
            thumbnail=(
                user.display_avatar.url if user.display_avatar else "https://none.none"
            ),
            fields=fields,  # type: ignore
            footer={"text": footer},
        )

    @command(
        name="hex", aliases=["dominant"], description="Get a hex code from an image."
    )
    async def hex(self, ctx: Context, *, user: User = None):  # type: ignore
        user = user or ctx.author
        image_url = None

        if ctx.message.attachments:
            image_url = ctx.message.attachments[0].url
        elif user.display_avatar:
            image_url = user.display_avatar.url
        else:
            image_url = ctx.author.display_avatar.url

        async with ctx.typing():
            try:
                response = requests.get(image_url)  # type: ignore
                image_bytes = io.BytesIO(response.content)
                image = Image.open(image_bytes)
                color_thief = ColorThief(image_bytes)
                dominant = color_thief.get_color(quality=1)

                hex_discord = int("0x{:02x}{:02x}{:02x}".format(*dominant), 16)
                hex = "#{:02x}{:02x}{:02x}".format(*dominant)

                return await ctx.embed(
                    title=f"Showing hex code: {hex}",
                    color=hex_discord,  # type: ignore
                    fields=[{"name": "RGB Value", "value": f"{dominant}"}],
                )
            except Exception as e:
                return await ctx.warn(f"An error occurred: `{e}`")

    @command(name="avatar", aliases=["av"], description="Get a user's avatar.")
    async def avatar(
        self, ctx: Context, *, user: Union[User, Member, str] = None
    ) -> Message:
        if user is None:
            user = ctx.author
        if isinstance(user, (User, Member)):
            member = ctx.guild.get_member(user.id) if ctx.guild else None
        else:
            if user:
                members = ctx.guild.members  # type: ignore
                member_names = [m.display_name for m in members]
                match = get_close_matches(
                    user.lower(),
                    [name.lower() for name in member_names],
                    n=1,
                    cutoff=0.5,
                )
                if match:
                    member = next(
                        m for m in members if m.display_name.lower() == match[0]
                    )
                else:
                    return await ctx.warn(f"No matching user found for `{user}`.")
                user = member
            else:
                user = ctx.author
                member = ctx.guild.get_member(user.id) if ctx.guild else None

        if not user:
            return await ctx.warn("No user found or matched.")

        return await ctx.embed(
            title=f"{user}'s avatar",
            url=user.display_avatar.url,
            image=user.display_avatar.url,
        )

    @command(name="banner", description="Get a user's banner.")
    async def banner(
        self, ctx: Context, *, user: Union[User, Member, str] = None
    ) -> Message:  # type: ignore
        if user is None:
            user = ctx.author
        if isinstance(user, (User, Member)):
            member = ctx.guild.get_member(user.id) if ctx.guild else None
        else:
            if user:
                members = ctx.guild.members  # type: ignore
                member_names = [m.display_name for m in members]
                match = get_close_matches(
                    user.lower(),
                    [name.lower() for name in member_names],
                    n=1,
                    cutoff=0.5,
                )
                if match:
                    member = next(
                        m for m in members if m.display_name.lower() == match[0]
                    )
                else:
                    return await ctx.warn(f"No matching user found for `{user}`.")
                user = member
            else:
                user = ctx.author
                member = ctx.guild.get_member(user.id) if ctx.guild else None

        if not user:
            return await ctx.warn("No user found or matched.")

        user = await self.bot.fetch_user(user.id)

        if user.banner:
            embed = discord.Embed(
                title=f"{user.name}'s banner", color=COLORS.neutral, url=user.banner.url
            )
            embed.set_image(url=user.banner.url)
            await ctx.send(embed=embed)
        else:
            await ctx.warn(f"This user does not have a banner set.")

    @command(
        name="serverinfo",
        aliases=["si"],
        description="Get information about the server",
    )
    async def serverinfo(self, ctx: Context):
        premium_tier = ctx.guild.premium_tier  # type: ignore

        if premium_tier == 0:
            role_limit = 250
        elif premium_tier == 1:
            role_limit = 250
        elif premium_tier == 2:
            role_limit = 500
        elif premium_tier == 3:
            role_limit = 2500

        return await ctx.embed(
            title=f"{ctx.guild.name}",  # type: ignore
            description=f"Server created on {format_dt(ctx.guild.created_at, 'D')} ({format_dt(ctx.guild.created_at, 'R')})",  # type: ignore
            fields=[
                {
                    "name": "Owner",
                    "value": f"{ctx.guild.owner.mention} \n({ctx.guild.owner.id})",  # type: ignore
                    "inline": True,
                },
                {
                    "name": "Members",
                    "value": f"**Total:** {ctx.guild.member_count} \n**Humans:** {sum(1 for member in ctx.guild.members if not member.bot)} \n**Bots:** {sum(1 for member in ctx.guild.members if member.bot)}",  # type: ignore
                    "inline": True,
                },
                {
                    "name": "Information",
                    "value": f"**Verification:** {ctx.guild.verification_level} \n**Boosts:** {ctx.guild.premium_subscription_count}",  # type: ignore
                    "inline": True,
                },
                {
                    "name": "Design",
                    "value": f"**Splash:** [click here]({ctx.guild.splash.url if ctx.guild.splash else 'https://none.none'}) \n**Banner:** [click here]({ctx.guild.banner.url if ctx.guild.banner else 'https://none.none'}) \n**Icon:** [click here]({ctx.guild.icon.url if ctx.guild.icon else 'https://none.none'})",  # type: ignore
                    "inline": True,
                },
                {
                    "name": f"Channels ({len(ctx.guild.channels)})",  # type: ignore
                    "value": f"**Text:** {len(ctx.guild.text_channels)} \n**Voice:** {len(ctx.guild.voice_channels)} \n**Categories:** {len(ctx.guild.categories)}",  # type: ignore
                    "inline": True,
                },
                {
                    "name": "Counts",
                    "value": f"**Roles:** {len(ctx.guild.roles)}/{role_limit} \n**Emojis:** {len(ctx.guild.emojis)}/{ctx.guild.emoji_limit} \n**Boosters:** {len(ctx.guild.premium_subscribers)}",  # type: ignore
                    "inline": True,
                },
            ],
            thumbnail=ctx.guild.icon.url if ctx.guild.icon else "https://none.none",  # type: ignore
            author={
                "name": ctx.author.display_name,
                "icon_url": ctx.author.display_avatar.url,
            },
        )

    @command(
        name="ping",
        aliases=["latency", "websocket"],
        description="Get the latency of the bot",
    )
    async def ping(self, ctx: Context):
        pings = "./base/data/pings.txt"  # replace with your file path
        with open(pings, "r") as f:
            lines = f.readlines()
            randomping = choice(lines).strip()
        start = time.time()
        latency_ms = self.bot.ping
        message = await ctx.send(content="ping...")
        finished = time.time() - start
        edit_ms = round(finished * 1000, 1)
        return await message.edit(
            content=f"it took `{latency_ms}ms` to ping **{randomping}** (edit: `{edit_ms}ms`)"
        )

    @hybrid_group(
        name="boosters",
        invoke_without_command=True,
        description="See a list of boosters in the guild",
    )
    async def boosters(self, ctx: Context):
        boosters = ctx.guild.premium_subscribers  # type: ignore
        if not boosters:
            return await ctx.warn(f"There are no **boosters** in this guild.")

        entries = []
        for i, member in enumerate(boosters, start=1):
            boosted_at = member.premium_since
            boosted_ago = naturaltime(boosted_at) if boosted_at else "Unknown"
            entries.append(f"`{i}`  **{member.name}** - Boosted: **{boosted_ago}**")

        total_pages = (len(entries) + 9) // 10  # Calculates total pages, rounding up.
        embeds = []
        count = 0
        embed = discord.Embed(
            color=COLORS.neutral, title=f"Boosters ({len(entries)})", description=""
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                    )
                )
                embed = discord.Embed(
                    color=COLORS.neutral,
                    title=f"Boosters ({len(entries)})",
                    description="",
                )
                count = 0

        if count > 0:
            embeds.append(
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                )
            )

        if len(embeds) > 1:
            await ctx.paginate(embeds)
        else:
            await ctx.send(embed=embeds[0])

    @Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Check if the boost status has been removed."""
        if before.premium_since and not after.premium_since:
            await self.bot.log_lost_boost(before)

    @boosters.command(
        name="lost", description="Check how many boosters the guild has lost."
    )
    async def boosters_lost(self, ctx: Context):
        guild_id = ctx.guild.id  # type: ignore
        query = """
        SELECT user_id, username, discriminator, lost_at
        FROM lost_boosters
        WHERE guild_id = $1
        ORDER BY lost_at DESC
        """
        lost_boosters = await self.bot.pool.fetch(query, guild_id)

        if not lost_boosters:
            return await ctx.warn("No boosters have lost their boost in this guild.")

        embeds = []
        count = 0
        entries = []

        for i, row in enumerate(lost_boosters, start=1):
            user_id = row["user_id"]
            username = row["username"]
            discriminator = row["discriminator"]
            lost_at = row["lost_at"]
            lost_ago = naturaltime(lost_at)

            entries.append(
                f"`{i}`  **{username}#{discriminator}** - Lost Boost: **{lost_ago}**"
            )

        embed = discord.Embed(
            color=COLORS.neutral,
            title=f"Lost Boosters ({len(entries)})",
            description="",
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(embed)
                embed = discord.Embed(
                    color=COLORS.neutral,
                    description="",
                    title=f"Lost Boosters ({len(entries)})",
                )
                count = 0

        if count > 0:
            embeds.append(embed)

        await ctx.paginate(embeds)

    @command(
        name="membercount",
        aliases=["mc"],
        description="Get the member count of the guild.",
    )
    async def membercount(self, ctx: Context):
        total_members = ctx.guild.member_count  # type: ignore
        bot_count = sum(1 for member in ctx.guild.members if member.bot)  # type: ignore
        user_count = total_members - bot_count  # type: ignore

        bot_percentage = (bot_count / total_members) * 100 if total_members > 0 else 0  # type: ignore
        user_percentage = (user_count / total_members) * 100 if total_members > 0 else 0  # type: ignore
        return await ctx.embed(
            title=f"",
            description=f"**Members:** `{ctx.guild.member_count}` \n**Users:** `{sum(1 for member in ctx.guild.members if not member.bot)}` ({user_percentage:.2f}%)\n**Bots:** `{sum(1 for member in ctx.guild.members if member.bot)}` ({bot_percentage:.2f}%)",  # type: ignore
        )

    @command(
        name="roleinfo",
        aliases=["rinfo", "ri"],
        description="Get information about a role",
    )
    async def roleinfo(self, ctx: Context, role: Role):
        return await ctx.embed(
            title=role.name,
            fields=[
                {"name": "Role ID", "value": f"`{role.id}`", "inline": True},
                {
                    "name": "Guild",
                    "value": f"{role.guild.name} (`{role.guild.id}`)",
                    "inline": True,
                },
                {"name": "Color", "value": f"{role.color}", "inline": True},
                {
                    "name": "Creation Date",
                    "value": f"{format_dt(role.created_at, 'D')} (**{format_dt(role.created_at, 'R')}**)",
                },
                {
                    "name": f"{len(role.members)} Member(s)",
                    "value": ", ".join([member.name for member in role.members]),
                },
            ],
            author={
                "name": ctx.author.display_name,
                "icon_url": ctx.author.display_avatar.url,
            },
            thumbnail=role.icon.url if role.icon else "https://none.none",
        )

    @command(
        name="serveravatar",
        aliases=["serverav", "sav"],
        description="Get a user's server avatar",
    )
    async def serveravatar(
        self, ctx: Context, *, user: Union[User, Member, str] = None
    ) -> Message:
        if user is None:
            user = ctx.author
        if isinstance(user, (User, Member)):
            member = ctx.guild.get_member(user.id) if ctx.guild else None
        else:
            if user:
                members = ctx.guild.members  # type: ignore
                member_names = [m.display_name for m in members]
                match = get_close_matches(
                    user.lower(),
                    [name.lower() for name in member_names],
                    n=1,
                    cutoff=0.5,
                )
                if match:
                    member = next(
                        m for m in members if m.display_name.lower() == match[0]
                    )
                else:
                    return await ctx.warn(f"No matching user found for `{user}`.")
                user = member
            else:
                user = ctx.author
                member = ctx.guild.get_member(user.id) if ctx.guild else None

        if not user:
            return await ctx.warn("No user found or matched.")

        if not user.guild_avatar:  # type: ignore
            return await ctx.warn(f"{user} doesn't have a **server avatar** set.")

        return await ctx.embed(
            title=f"{user}'s server avatar",
            image=user.guild_avatar.url,  # type: ignore
            url=user.guild_avatar.url,  # type: ignore
        )

    @command(
        name="serverbanner",
        aliases=["sbanner"],
        description="Get a user's server banner.",
    )
    async def serverbanner(
        self, ctx: Context, *, user: Union[User, Member, str] = None
    ) -> Message:
        if user is None:
            user = ctx.author
        if isinstance(user, (User, Member)):
            member = ctx.guild.get_member(user.id) if ctx.guild else None
        else:
            if user:
                members = ctx.guild.members  # type: ignore
                member_names = [m.display_name for m in members]
                match = get_close_matches(
                    user.lower(),
                    [name.lower() for name in member_names],
                    n=1,
                    cutoff=0.5,
                )
                if match:
                    member = next(
                        m for m in members if m.display_name.lower() == match[0]
                    )
                else:
                    return await ctx.warn(f"No matching user found for `{user}`.")
                user = member
            else:
                user = ctx.author
                member = ctx.guild.get_member(user.id) if ctx.guild else None

        if not user:
            return await ctx.warn("No user found or matched.")

        if not user.guild_banner:  # type: ignore
            return await ctx.warn(f"{user} doesn't have a **server banner** set.")

        return await ctx.embed(
            title=f"{user}'s server banner",
            url=user.guild_banner.url,  # type: ignore
            image=user.guild_banner.url,  # type: ignore
        )

    @command(name="bots", description="Get a list of bots.")
    async def bots(self, ctx: Context):
        bots = [b for b in ctx.guild.members if b.bot]  # type: ignore
        count = 0
        embeds = []

        entries = [f"`{i}`  **{m.name}**" for i, m in enumerate(bots, start=1)]
        embed = discord.Embed(
            color=COLORS.neutral, title=f"List of bots ({len(entries)})", description=""
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(embed)
                embed = discord.Embed(
                    color=COLORS.neutral,
                    description="",
                    title=f"List of bots ({len(entries)})",
                )
                count = 0

        if count > 0:
            embeds.append(embed)

        await ctx.paginate(embeds)

    @command(
        name="botinfo",
        aliases=["about", "info", "bi"],
        description="Get information about the bot.",
    )
    async def botinfo(self, ctx: Context):
        return await ctx.embed(
            author={
                "name": ctx.author.display_name,
                "icon_url": (
                    ctx.author.display_avatar.url
                    if ctx.author.display_avatar
                    else "https://none.none"
                ),
            },
            fields=[
                {
                    "name": "Bot",
                    "value": f"Users: **{len(self.bot.users):,}** \nServers: **{len(self.bot.guilds):,}** \nPing: **{self.bot.ping}ms**",
                    "inline": True,
                },
                {
                    "name": "Info",
                    "value": f"RAM: **{self.bot.format_size(Process().memory_info().rss)}** \nCPU: **{Process().cpu_percent()}%** \nBooted: **{self.bot.booted}**",
                    "inline": True,
                },
            ],
            thumbnail=(
                self.bot.user.display_avatar.url
                if self.bot.user.display_avatar
                else "https://none.none"
            ),  # type: ignore
            footer={
                "text": f"Commands: {len([cmd for cmd in self.bot.walk_commands() if cmd.cog_name != 'Jishaku'])} | lines: {self.bot.linecount: ,}"
            },
        )

    @command(name="bans", description="Get a list of banned users.")
    async def bans(self, ctx: Context):
        bans = [entry async for entry in ctx.guild.bans()]  # type: ignore
        count = 0
        embeds = []

        entries = [
            f"`{i}`  **{ban.user.name}** (`{ban.user.id}`) - Reason: {ban.reason if ban.reason else 'No reason provided'}"
            for i, ban in enumerate(bans, start=1)
        ]

        total_pages = (len(entries) + 9) // 10  # Calculates total pages, rounding up.
        embed = discord.Embed(
            color=COLORS.neutral,
            title=f"List of Banned Users ({len(entries)})",
            description="",
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            embed.set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
            )
            count += 1

            if count == 10:
                embeds.append(
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                    )
                )
                embed = discord.Embed(
                    color=COLORS.neutral,
                    title=f"List of Banned Users ({len(entries)})",
                    description="",
                )
                count = 0

        if count > 0:
            embeds.append(
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                )
            )

        if len(embeds) > 1:
            await ctx.paginate(embeds)
        else:
            await ctx.send(embed=embeds[0])

    @command(name="uptime", aliases=["up", "ut"], description="Get the bot's uptime")
    async def uptime(self, ctx: Context):
        return await ctx.embed(
            description=f"⏰ **{self.bot.user.display_name}** has been up for: {self.bot.humanize_time(self.bot._uptime)}"  # type: ignore
        )

    @command(name="invite", aliases=["inv"], description="Get the bots invite.")
    async def invite(self, ctx: Context):
        oauth_url = f"https://discord.com/oauth2/authorize?client_id={self.bot.user.id}&permissions={Permissions.all().value}&scope=bot"  # type: ignore
        button = discord.ui.Button(
            label="Invite",
            style=ButtonStyle.url,
            url=oauth_url,
            emoji=EMOJIS.INFORMATION,
        )

        view = discord.ui.View()
        view.add_item(button)

        await ctx.reply(view=view)

    @command(name="banreason", description="Get a user's ban reason.")
    @has_permissions(ban_members=True)
    async def banreason(self, ctx: Context, *, user: User):
        bans = [entry async for entry in ctx.guild.bans()]  # type: ignore
        entry = next((b for b in bans if b.user.id == user.id), None)

        if not entry:
            return await ctx.warn("This member is **not** banned.")

        return await ctx.embed(
            description=f"**{user.name}** was banned for **{entry.reason}**"
        )

    @command(name="status", description="Get a link to the status page")
    async def status(self, ctx: Context):
        return await ctx.send(
            f"{ctx.author.mention}: Experiencing issues? Check your shards status on https://Xrypton.best/status"
        )

    @hybrid_group(
        name="emoji",
        description="Returns a large emoji or server emote",
        invoke_without_command=True,
    )
    async def emoji(self, ctx: Context, *, emoji: PartialEmoji):
        return await ctx.send(
            file=await emoji.to_file(
                filename=f"{emoji.name}{'.gif' if emoji.animated else '.png'}"
            )
        )

    @emoji.command(
        name="steal",
        aliases=["copy", "add"],
        description="Downloads emote and adds to server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_steal(
        self, ctx: Context, emoji: PartialEmoji, *, name: str = None
    ):
        if not name:
            name = emoji.name

        try:
            emoji = await ctx.guild.create_custom_emoji(
                image=await emoji.read(), name=name
            )
            return await ctx.approve(f"Added **emote** {emoji}")
        except Exception as E:
            return await ctx.warn(f"{E}")

    @emoji.command(
        name="remove",
        aliases=["delete"],
        description="Remove an emoji from the server.",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_remove(self, ctx: Context, *, emoji: PartialEmoji):
        try:
            await emoji.delete()
            return await ctx.approve(f"Removed **emote** `{emoji.name}`")
        except Exception as E:
            return await ctx.warn(f"{E}")
