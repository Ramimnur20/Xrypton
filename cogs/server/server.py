from typing import Union
from re import compile
import asyncio

from base.context import Confirmation
from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice
from humanize import naturaltime
from loguru import logger
import humanize
from datetime import datetime
import time

from discord import (
    Embed,
    Member,
    Message,
    Permissions,
    Role,
    TextChannel,
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
from discord.ui import View, button
import discord
from discord.utils import format_dt, oauth_url
from base.managers.predicates import has_permissions

from psutil import Process
from difflib import get_close_matches

from PIL import Image
from colorthief import ColorThief
from base.managers.EmbedBuilder import *


def has_br_role():
    async def predicate(ctx: Context):
        check = await ctx.bot.pool.fetchrow(
            "SELECT * FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not check:
            await ctx.warn(
                f"You do not have a booster role set\nPlease use `{ctx.clean_prefix}br create` to create a booster role"
            )
        return check is not None

    return commands.check(predicate)

def level2():
    async def predicate(ctx: Context):
        if ctx.guild is not None and ctx.guild.premium_tier >= 2:
            return True
        else:
            await ctx.warn("This guild doesn't have level 2 boosts.")
            return False

    return commands.check(predicate)

def br_enabled():
    async def predicate(ctx: Context):
        check = await ctx.bot.pool.fetchrow(
            "SELECT 1 FROM booster_module WHERE guild_id = $1", ctx.guild.id
        )

        if check:
            return True
        else:
            await ctx.warn("The booster role module is not enabled in this guild.")
            return False

    return commands.check(predicate)

class Server(CogMeta):
    valid_perms = set(Permissions.VALID_FLAGS)
    
    @Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.bot.pool.execute("DELETE FROM br_award WHERE role_id = $1", role.id)

    @Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if (
            not before.guild.premium_subscriber_role in before.roles
            and before.guild.premium_subscriber_role in after.roles
        ):
            if results := await self.bot.pool.fetchrow(
                "SELECT role_id FROM br_award WHERE guild_id = $1", before.guild.id
            ):
                roles = [
                    after.guild.get_role(result["role_id"])
                    for result in results
                    if after.guild.get_role(result["role_id"]).is_assignable()
                ]
                await asyncio.gather(
                    *[
                        after.add_roles(role, reason="Booster role created")
                        for role in roles
                    ]
                )
            elif (
                before.guild.premium_subscriber_role in before.roles
                and not after.guild.premium_subscriber_role in after.roles
            ):
                if results := await self.bot.pool.fetchrow(
                    "SELECT role_id FROM br_award WHERE guild_id = $1", before.guild.id
                ):
                    roles = [
                        after.guild.get_role(
                            result["role_id"]
                            for result in results
                            if after.guild.get_role(result["role_id"]).is_assignable()
                            and after.guild.get_role(result["role_id"]) in after.roles
                        )
                    ]

                    await asyncio.gather(
                        *[
                            after.remove_roles(
                                role, reason="Removed booster role from this member."
                            )
                            for role in roles
                        ]
                    )

    @hybrid_group(
        name="welcome",
        aliases=["welc", "welcomer", "wlc"],
        invoke_without_command=True,
        description="Configure the welcome module",
    )
    @has_permissions(manage_messages=True)
    async def welcome(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @welcome.command(
        name="add", aliases=["create", "set"], description="Add a welcome message"
    )
    @has_permissions(manage_messages=True)
    async def welcome_add(
        self, ctx: Context, channel: discord.TextChannel, *, message: str
    ):  # type: ignore

        processed_message = EmbedBuilder.embed_replacement(ctx.author, message)  # type: ignore
        content, embed, view = await EmbedBuilder.to_object(processed_message)

        check = await self.bot.pool.fetchrow(
            """
            SELECT * FROM welcome WHERE channel_id = $1
            """,
            channel.id,
        )
        if check:
            await self.bot.pool.execute(
                """
                UPDATE welcome
                SET message = $1 
                WHERE channel_id = $2
                """,
                message,
                channel.id,
            )
            await ctx.approve(f"Edited {channel.mention}'s welcome message to:")
            if content or embed:
                return await ctx.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                return await ctx.send(content=processed_message)

        if ctx.guild:
            await self.bot.pool.execute(
                """
                INSERT INTO welcome 
                VALUES ($1, $2, $3) 
                """,
                ctx.guild.id,
                channel.id,
                message,
            )
            await ctx.approve(f"Added a welcome message in {channel.mention}.")
            if content or embed:
                return await ctx.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                return await ctx.send(content=processed_message)

    @welcome.command(
        name="remove", aliases=["delete", "del"], description="Remove a welcome message"
    )
    @has_permissions(manage_messages=True)
    async def welcome_remove(self, ctx: Context, *, channel: discord.TextChannel):
        if ctx.guild:
            data = await self.bot.pool.fetchrow(
                "SELECT * FROM welcome WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )

            if data:
                message = data["message"]

                await self.bot.pool.execute(
                    """
                    DELETE FROM welcome
                    WHERE guild_id = $1 AND channel_id = $2
                    """,
                    ctx.guild.id,
                    channel.id,
                )
                await ctx.approve(
                    f"Removed the **welcome settings** from {channel.mention}!"
                )
            else:
                return await ctx.warn(
                    f"There are no **welcome settings** saved for {channel.mention}."
                )

    @welcome.command(
        name="view", aliases=["test"], description="Test a welcome message"
    )
    @has_permissions(manage_messages=True)
    async def welcome_test(self, ctx: Context, channel: discord.TextChannel):
        res = await self.bot.pool.fetchrow(
            "SELECT * from welcome WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,  # type: ignore
        )

        if res:
            channel_id = res["channel_id"]
            channel = ctx.guild.get_channel(channel_id)  # type: ignore

            if channel is None:
                return

            message = res["message"]
            processed_message = EmbedBuilder.embed_replacement(ctx.author, message)  # type: ignore
            content, embed, view = await EmbedBuilder.to_object(processed_message)

            if content or embed:
                await channel.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                await channel.send(content=processed_message)

        else:
            return

    @welcome.command(
        name="list", description="Show a list of channels with a welcome message."
    )
    @has_permissions(manage_messages=True)
    async def welcome_list(self, ctx: Context):
        if ctx.guild:
            res = await self.bot.pool.fetch(
                """
                SELECT channel_id, message FROM welcome WHERE guild_id = $1
                """,
                ctx.guild.id,
            )

            if not res:
                return await ctx.warn(
                    "There are no welcome messages set up in this guild."
                )

            entries = [
                f"`{i}` {self.bot.get_channel(entry['channel_id']).mention if self.bot.get_channel(entry['channel_id']) else 'Channel ID: ' + str(entry['channel_id'])} (`{entry['channel_id']}`)"  # type: ignore
                for i, entry in enumerate(res, start=1)
            ]

            embeds = []
            embed = discord.Embed(
                color=COLORS.neutral, title="Welcome channels", description=""
            )

            count = 0
            for entry in entries:
                embed.description += f"{entry}\n"  # type: ignore
                count += 1

                if count == 5:
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} (entries: {len(entries)})"
                    )
                    embed.set_author(
                        name=ctx.author.display_name,
                        icon_url=ctx.author.display_avatar.url,
                    )
                    embeds.append(embed)
                    embed = discord.Embed(
                        color=COLORS.neutral, title=f"Welcome channels", description=""
                    )
                    count = 0

            if count > 0:
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} ({len(entries)} entries)"
                )
                embed.set_author(
                    name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
                )
                embeds.append(embed)

            if len(embeds) > 1:
                await ctx.paginate(embeds)
            else:
                await ctx.send(embed=embeds[0])

    @welcome.command(
        name="variables", description="Show available variables for welcome messages."
    )
    @has_permissions(manage_messages=True)
    async def welcome_variables(self, ctx: Context):
        embed = discord.Embed(
            color=COLORS.neutral,
            title="Welcome Variables",
            description="",
        )
        embed.add_field(
            name="User",
            value=(
                "`{user}`, `{user.name}`, `{user.mention}`, `{user.avatar}`, "
                "`{user.discriminator}`, `{user.joined_at}`, `{user.created_at}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Guild",
            value=(
                "`{guild.name}`, `{guild.count}`, `{guild.count.format}`, "
                "`{guild.id}`, `{guild.created_at}`, `{guild.boost_count}`, "
                "`{guild.boost_count.format}`, `{guild.booster_count}`, "
                "`{guild.booster_count.format}`, `{guild.boost_tier}`, "
                "`{guild.vanity}`, `{guild.icon}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Special",
            value="`{invisible}`, `{botcolor}`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @hybrid_group(
        name="prefix",
        invoke_without_command=True,
        description="See the prefix in the server",
    )
    async def prefix(self, ctx: Context):
        prefix = (
            await self.bot.pool.fetchval(
                "SELECT prefix FROM prefix WHERE guild_id = $1", ctx.message.guild.id
            )
            or ","
        )
        return await ctx.embed(
            description=f"{ctx.author.mention}: **Guild prefix:** `{prefix}`"
        )

    @prefix.command(name="add", aliases=["set"], description="Change the prefix")
    @has_permissions(manage_messages=True)
    async def prefix_add(self, ctx: Context, *, prefix: str):
        await self.bot.pool.execute(
            "INSERT OR REPLACE INTO prefix VALUES (?, ?)",
            ctx.guild.id,
            str(prefix),
        )
        return await ctx.approve(f"**Server prefix** updated to: `{prefix}`")

    @prefix.command(
        name="remove", aliases=["reset"], description="Reset the prefix back to default"
    )
    @has_permissions(manage_messages=True)
    async def prefix_remove(self, ctx: Context):
        await self.bot.pool.execute(
            "DELETE FROM prefix WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.approve(f"**Server prefix** updated to: `,`")

    @hybrid_group(name="alias", invoke_without_command=True, description="Configure aliases")
    @has_permissions(manage_guild=True)
    async def alias(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @alias.command(name="add", description="Add a custom alias")
    @has_permissions(manage_guild=True)
    async def alias_add(self, ctx: Context, alias: str, *, command: str):
        alias = alias.lower().replace(" ", "")

        if self.bot.get_command(alias):
            return await ctx.warn(f"`{alias}` is a **registered command**!")

        _command = self.bot.get_command(
            compile(r"[a-zA-Z0-9 ]+").match(command).group()
        )
        if not _command:
            return await ctx.warn(f"`{_command}` is not a **command**.")

        if not await self.bot.pool.fetchval(
            """
            SELECT * FROM aliases WHERE guild_id = $1 AND alias = $2
            """,
            ctx.guild.id,
            alias,
        ):
            await self.bot.pool.execute(
                """
                INSERT INTO aliases (guild_id, alias, command) 
                VALUES ($1, $2, $3)
                """,
                ctx.guild.id,
                alias,
                _command.qualified_name,
            )
            return await ctx.approve(f"Added **{alias}** for `{_command}`.")

    @alias.command(name="remove", description="Remove a custom alias")
    @has_permissions(manage_guild=True)
    async def alias_remove(self, ctx: Context, alias: str):
        alias = alias.lower().replace(" ", "")

        if not await self.bot.pool.fetchval(
            """
            SELECT * FROM aliases WHERE guild_id = $1 AND alias = $2
            """,
            ctx.guild.id,
            alias,
        ):
            return await ctx.warn(f"`{alias}` is not an existing **alias**.")

        await self.bot.pool.execute(
            """
            DELETE FROM aliases WHERE guild_id = $1 AND alias = $2
            """,
            ctx.guild.id,
            alias,
        )
        return await ctx.approve(f"Removed **alias** `{alias}`")

    @alias.command(name="list", description="Get a list of your guild's custom aliases")
    async def alias_list(self, ctx: Context):
        rows = await self.bot.pool.fetch(
            """
        SELECT alias, command, invoke
        FROM aliases
        WHERE guild_id = $1
        """,
            ctx.guild.id,
        )

        if not rows:
            return await ctx.warn("There are no **aliases** set up.")

        embeds = []
        entries = []
        count = 0

        for i, row in enumerate(rows, start=1):
            alias = row["alias"]
            command = row["command"]

            entries.append(f"`{i}` **{alias}** executes `{command}`")

        total_pages = (len(entries) + 9) // 10

        if not entries:
            return await ctx.warn("There are no valid aliases to display.")

        embed = discord.Embed(color=COLORS.neutral, title=f"", description="")
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed.set_footer(
            text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(embed)
                embed = discord.Embed(
                    color=COLORS.neutral,
                    description="",
                    title=f"Aliases",
                )
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{total_pages} ({len(entries)} entries)"
                )
                embed.set_author(
                    name=ctx.author.name, icon_url=ctx.author.display_avatar.url
                )
                count = 0

        if count > 0:
            embeds.append(embed)

        if len(embeds) > 1:
            await ctx.paginate(embeds)
        elif embeds:
            await ctx.send(embed=embeds[0])

    @hybrid_group(
        name="autorole",
        invoke_without_command=True,
        description="Configure autorole",
    )
    @has_permissions(manage_roles=True)
    async def autorole(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @autorole.command(name="add", aliases=["create"], description="Add an autorole")
    @has_permissions(manage_roles=True)
    async def autorole_add(self, ctx: Context, *, role: Role):
        if await self.bot.pool.fetchval(
            """
            SELECT * 
            FROM autorole
            WHERE guild_id = $1 AND role_id = $2
            """,
            ctx.guild.id,
            role.id,
        ):
            return await ctx.warn(f"{role.mention} is already an **auto role**.")

        await self.bot.pool.execute(
            """
            INSERT INTO autorole (guild_id, role_id)
            VALUES ($1, $2)
            """,
            ctx.guild.id,
            role.id,
        )
        return await ctx.approve(
            f"{role.mention} will now be assigned to **new members**."
        )

    @autorole.command(
        name="remove", aliases=["delete", "del"], description="Remove an autorole"
    )
    @has_permissions(manage_roles=True)
    async def autorole_remove(self, ctx: Context, *, role: Role):
        if not await self.bot.pool.fetchval(
            """
            SELECT * 
            FROM autorole 
            WHERE guild_id = $1 AND role_id = $2
            """,
            ctx.guild.id,
            role.id,
        ):
            return await ctx.warn(f"{role.mention} is not an **auto role**.")

        await self.bot.pool.execute(
            """
            DELETE FROM autorole
            WHERE guild_id = $1 AND role_id = $2
            """,
            ctx.guild.id,
            role.id,
        )
        return await ctx.approve(
            f"{role.mention} will no longer be assigned to **new members**."
        )

    @autorole.command(name="list", description="See a list of autoroles in the guild")
    @has_permissions(manage_roles=True)
    async def autorole_list(self, ctx: Context):
        rows = await self.bot.pool.fetch(
            """
            SELECT role_id
            FROM autorole
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )

        role_ids = [row["role_id"] for row in rows]
        roles = [ctx.guild.get_role(role_id) for role_id in role_ids]

        embeds = []
        entries = []
        count = 0

        if not roles:
            return await ctx.warn("There are no **auto roles** set up.")

        for i, role in enumerate(roles, start=1):
            if role:
                entries.append(f"`{i}`  **{role.mention}**")

        if not entries:
            return await ctx.warn("There are no valid roles to display.")

        embed = discord.Embed(
            color=COLORS.neutral, title=f"Autoroles ({len(entries)})", description=""
        )

        for entry in entries:
            embed.description += f"{entry}\n"  # type: ignore
            count += 1

            if count == 10:
                embeds.append(embed)
                embed = discord.Embed(
                    color=COLORS.neutral,
                    description="",
                    title=f"Autoroles ({len(entries)})",
                )
                count = 0

        if count > 0:
            embeds.append(embed)

        if len(embeds) > 1:
            await ctx.paginate(embeds)
        elif embeds:
            await ctx.send(embed=embeds[0])

    @Cog.listener("on_member_join")
    async def autorole_listener(self, member: Member):
        role_ids = await self.bot.pool.fetch(
            """
        SELECT role_id
        FROM autorole 
        WHERE guild_id = $1
        """,
            member.guild.id,
        )

        if role_ids:
            for row in role_ids:
                role_id = row["role_id"]
                role = member.guild.get_role(role_id)

                if role and role not in member.roles:
                    try:
                        await member.add_roles(role)
                    except Exception:
                        pass

    @Cog.listener("on_member_join")
    async def welcome_listener(self, member: discord.Member):
        res = await self.bot.pool.fetch(
            "SELECT * FROM welcome WHERE guild_id = $1", member.guild.id
        )
        for result in res:
            channel = self.bot.get_channel(result["channel_id"])
            if channel:
                processed_message = EmbedBuilder.embed_replacement(
                    member, result["message"]
                )  # type: ignore
                content, embed, view = await EmbedBuilder.to_object(processed_message)
                if content or embed:
                    await channel.send(content=content, embed=embed, view=view)  # type: ignore
                else:
                    await channel.send(content=processed_message)  # type: ignore
                await asyncio.sleep(0.4)

    @hybrid_group(
        name="stickymessage",
        aliases=["sticky"],
        description="Set up a sticky message in one or multiple channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def stickymessage(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @stickymessage.command(name="add", description="Add a sticky message to a channel")
    @has_permissions(manage_guild=True)
    async def stickymessage_add(
        self, ctx: Context, channel: TextChannel, *, message: str
    ):
        if await self.bot.pool.fetchval(
            """
            SELECT channel_id FROM sticky_messages WHERE guild_id = $1
            """,
            ctx.guild.id,
        ):
            return await ctx.warn(
                f" Theres already a **sticky message** for this channel, you can't have multiple for one channel. Remove the current **sticky message** then try again."
            )

        processed_message = EmbedBuilder.embed_replacement(ctx.author, message)  # type: ignore
        content, embed, view = await EmbedBuilder.to_object(processed_message)

        if content or embed:
            _message = await ctx.send(content=content, embed=embed, view=view)  # type: ignore
        else:
            _message = await ctx.send(content=processed_message)

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO sticky_messages (guild_id, channel_id, message_id, message)
            VALUES (?, ?, ?, ?)
            """,
            ctx.guild.id,
            channel.id,
            _message.id,
            str(message),
        )

    @stickymessage.command(
        name="remove", description="Remove a sticky message from a channel"
    )
    @has_permissions(manage_guild=True)
    async def stickymessage_remove(self, ctx: Context, channel: TextChannel):
        message = await self.bot.pool.fetchval(
            """
        SELECT message FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2
        """,
            ctx.guild.id,
            channel.id,
        )

        if not message:
            return await ctx.warn(
                f"No **sticky messages** found for {channel.mention}."
            )

        await self.bot.pool.execute(
            """
            DELETE FROM sticky_messages
            WHERE guild_id = $1 AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        return await ctx.approve(
            f"Removed the **sticky message** for {channel.mention}"
        )

    @Cog.listener("on_message")
    async def dispatch_stickymessage(self, message: discord.Message):
        if message.author.bot:
            return
        data = await self.bot.pool.fetchrow(
            "SELECT * FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        )

        if not data:
            return

        old = await message.channel.fetch_message(data["message_id"])
        await old.delete()

        if data["channel_id"] == message.channel.id:
            processed_message = EmbedBuilder.embed_replacement(message.author, data["message"])  # type: ignore
            content, embed, view = await EmbedBuilder.to_object(processed_message)

            if content or embed:
                new_message = await message.channel.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                new_message = await message.channel.send(content=processed_message)  # type: ignore

            await self.bot.pool.execute(
                "UPDATE sticky_messages SET message_id = $3 WHERE guild_id = $1 AND channel_id = $2",
                message.guild.id,
                message.channel.id,
                new_message.id,
            )

    @hybrid_group(
        name="boosts",
        aliases=["boost"],
        description="Set up boost messages in one or multiple channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def boosts(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @boosts.command(name="add", description="Add a boost message to a channel")
    @has_permissions(manage_messages=True)
    async def boosts_add(self, ctx: Context, channel: TextChannel, *, message: str):
        processed_message = EmbedBuilder.embed_replacement(ctx.author, message)  # type: ignore
        content, embed, view = await EmbedBuilder.to_object(processed_message)

        check = await self.bot.pool.fetchrow(
            """
            SELECT * FROM boost WHERE channel_id = $1
            """,
            channel.id,
        )
        if check:
            await self.bot.pool.execute(
                """
                UPDATE boost
                SET message = $1 
                WHERE channel_id = $2
                """,
                message,
                channel.id,
            )
            await ctx.approve(f"Edited {channel.mention}'s boost message to:")
            if content or embed:
                return await ctx.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                return await ctx.send(content=processed_message)

        if ctx.guild:
            await self.bot.pool.execute(
                """
                    INSERT INTO boost 
                    VALUES ($1, $2, $3) 
                    """,
                ctx.guild.id,
                channel.id,
                message,
            )
            await ctx.approve(f"Added a boost message in {channel.mention}.")
            if content or embed:
                return await ctx.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                return await ctx.send(content=processed_message)

    @boosts.command(
        name="remove",
        aliases=["delete", "del"],
        description="Remove a boost message from a channel",
    )
    @has_permissions(manage_messages=True)
    async def boosts_remove(self, ctx: Context, *, channel: discord.TextChannel):
        if ctx.guild:
            data = await self.bot.pool.fetchrow(
                "SELECT * FROM boost WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )

            if data:
                message = data["message"]

                await self.bot.pool.execute(
                    """
                    DELETE FROM boost
                    WHERE guild_id = $1 AND channel_id = $2
                    """,
                    ctx.guild.id,
                    channel.id,
                )
                await ctx.approve(
                    f"Removed the **boost settings** from {channel.mention}!"
                )
            else:
                return await ctx.warn(
                    f"There are no **boost settings** saved for {channel.mention}."
                )

    @boosts.command(
        name="view", aliases=["test"], description="View a boost message for a channel"
    )
    @has_permissions(manage_messages=True)
    async def boosts_view(self, ctx: Context, channel: discord.TextChannel):
        res = await self.bot.pool.fetchrow(
            "SELECT * from boost WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,  # type: ignore
        )

        if res:
            channel_id = res["channel_id"]
            channel = ctx.guild.get_channel(channel_id)  # type: ignore

            if channel is None:
                return

            message = res["message"]
            processed_message = EmbedBuilder.embed_replacement(ctx.author, message)  # type: ignore
            content, embed, view = await EmbedBuilder.to_object(processed_message)

            if content or embed:
                await channel.send(content=content, embed=embed, view=view)  # type: ignore
            else:
                await channel.send(content=processed_message)
            await ctx.message.add_reaction("✅")

        else:
            return

    @boosts.command(
        name="list", description="Show a list of channels with a boost message."
    )
    @has_permissions(manage_messages=True)
    async def boosts_list(self, ctx: Context):
        if ctx.guild:
            res = await self.bot.pool.fetch(
                """
                SELECT channel_id, message FROM boost WHERE guild_id = $1
                """,
                ctx.guild.id,
            )

            if not res:
                return await ctx.warn(
                    "There are no **boost messages** set up in this guild."
                )

            entries = [
                f"`{i}` {self.bot.get_channel(entry['channel_id']).mention if self.bot.get_channel(entry['channel_id']) else 'Channel ID: ' + str(entry['channel_id'])} (`{entry['channel_id']}`)"  # type: ignore
                for i, entry in enumerate(res, start=1)
            ]

            embeds = []
            embed = discord.Embed(
                color=COLORS.neutral, title="Boost channels", description=""
            )

            count = 0
            for entry in entries:
                embed.description += f"{entry}\n"  # type: ignore
                count += 1

                if count == 5:
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} (entries: {len(entries)})"
                    )
                    embed.set_author(
                        name=ctx.author.display_name,
                        icon_url=ctx.author.display_avatar.url,
                    )
                    embeds.append(embed)
                    embed = discord.Embed(
                        color=COLORS.neutral, title=f"Boost channels", description=""
                    )
                    count = 0

            if count > 0:
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} ({len(entries)} entries)"
                )
                embed.set_author(
                    name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
                )
                embeds.append(embed)

            if len(embeds) > 1:
                await ctx.paginate(embeds)
            else:
                await ctx.send(embed=embeds[0])

    @Cog.listener("on_message")
    async def dispatch_boosts(self, message: Message):
        if "MessageType.premium_guild" in str(message.type):
            data = await self.bot.pool.fetchrow(
                """
                SELECT * FROM boost WHERE guild_id = $1
                """,
                message.guild.id,
            )
            for result in data:
                channel = self.bot.get_channel(result["channel_id"])
                if channel:
                    processed_message = EmbedBuilder.embed_replacement(
                        message.author, result["message"]
                    )  # type: ignore
                    content, embed, view = await EmbedBuilder.to_object(
                        processed_message
                    )
                    if content or embed:
                        await channel.send(content=content, embed=embed, view=view)  # type: ignore
                    else:
                        await channel.send(content=processed_message)  # type: ignore
                    await asyncio.sleep(0.4)

    @hybrid_group(name = "autoresponder", aliases = ["autorespond", "autoresponse", "ar"], description = "Set up automatic replies to messages matching a trigger", invoke_without_command = True)
    @has_permissions(manage_messages = True)
    async def autoresponder(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    
    @autoresponder.command(name = "add", description = "Add an autoresponder")
    @has_permissions(manage_messages = True)
    async def autoresponder_add(self, ctx: Context, *, args: str):
        split_args = args.split()

        if len(split_args) < 2:
            return await ctx.warn(
                "Invalid syntax! Use: `,autoresponder add <trigger> <response> --flags`"
            )

        trigger = split_args[0]
        response = split_args[1]
        flags = split_args[2:]

        not_strict = False
        self_destruct = False
        self_destruct_time = 0
        delete_trigger = False
        reply = False

        i = 0
        while i < len(flags):
            flag = flags[i]
            if flag == "--not_strict":
                not_strict = True
            elif flag == "--self_destruct":
                try:
                    self_destruct_time = int(flags[i + 1])
                    self_destruct = True
                    i += 1
                except (IndexError, ValueError):
                    return await ctx.warn("Invalid value for `--self_destruct`. Use: `--self_destruct <Seconds>`")
            elif flag == "--delete_trigger":
                delete_trigger = True
            elif flag == "--reply":
                reply = True
            else:
                return await ctx.warn(f"Unknown flag: `{flag}`. Use `--not_strict`, `--self_destruct`, `--delete_trigger`, or `--reply`.")
            i += 1

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM autoresponders WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        if res:
            return await ctx.warn(f"An autoresponder with the trigger `{trigger}` already exists.")

        await self.bot.pool.execute(
            "INSERT INTO autoresponders (guild_id, trigger, response, not_strict, self_destruct, self_destruct_time ,delete_trigger, reply) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            ctx.guild.id,
            trigger,
            response,
            not_strict,
            self_destruct,
            self_destruct_time,
            delete_trigger,
            reply,
        )

        return await ctx.approve(
            f"Added new autoresponder with trigger `{trigger}` and response `{response}`. {'(Not Strict)' if not_strict else '(Strict match)'} {'(Delete)' if delete_trigger else ''} {'(Reply)' if reply else ''}"
            f"{f' This **autoresponder** will self-destruct in **{self_destruct_time}** seconds' if self_destruct else ''}"
        )
    
    @Cog.listener("on_message")
    async def dispatch_autoresponder(self, message: Message):
        if message.author.bot:
            return

        res = await self.bot.pool.fetchrow(
            "SELECT * FROM autoresponders WHERE guild_id = $1 AND trigger = $2",
            message.guild.id,
            message.content.split()[0], 
        )

        if not res:
            return

        response = res["response"]
        not_strict = res["not_strict"]
        self_destruct = res["self_destruct"]
        destruct =res["self_destruct_time"] if res["self_destruct_time"] else 0
        delete_trigger = res["delete_trigger"]
        reply = res["reply"]

        if not not_strict and message.content != res["trigger"]:
            return

        sent_msg = None
        if reply:
            sent_msg = await message.reply(response)
        else:
            sent_msg = await message.channel.send(response)

        if delete_trigger:
            await message.delete()

        if self_destruct and sent_msg and destruct > 0:
            await asyncio.sleep(int(destruct * 1))
            await sent_msg.delete()

    @autoresponder.command(name = "delete", aliases = ["remove"], description = "Delete an autoresponder")
    @has_permissions(manage_permissions = True)
    async def autoresponder_delete(self, ctx: Context, *, trigger: str):
        res = await self.bot.pool.fetchrow(
        "SELECT * FROM autoresponders WHERE guild_id = $1 AND trigger = $2",
        ctx.guild.id,
        trigger,
    )

        if not res:
            return await ctx.warn(f"No **autoresponder** found with the trigger `{trigger}`.")

        await self.bot.pool.execute(
            "DELETE FROM autoresponders WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        await ctx.approve(f"Deleted the **autoresponder** with trigger `{trigger}`.")


    @autoresponder.command(name="list", description="Show a list of autoresponders in this server.")
    @has_permissions(manage_messages=True)
    async def autoresponder_list(self, ctx: Context):
        if ctx.guild:
            res = await self.bot.pool.fetch(
                """
                SELECT trigger, response, not_strict, self_destruct, self_destruct_time, delete_trigger, reply 
                FROM autoresponders 
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )

            if not res:
                return await ctx.warn("There are no autoresponders set up in this guild.")

            entries = [
                f"`{i}` **{entry['trigger']}** (sd: {entry['self_destruct_time'] if entry['self_destruct'] else 'None'}, "
                f"strict: {'yes' if entry['not_strict'] else 'no, '}"
                f"reply: {'yes' if entry['reply'] else 'no'})"
                for i, entry in enumerate(res, start=1)
            ]

            embeds = []
            embed = discord.Embed(
                color=COLORS.neutral, title="Autoresponders", description=""
            )

            count = 0
            for entry in entries:
                embed.description += f"{entry}\n"
                count += 1

                if count == 5:
                    embed.set_footer(
                        text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} (Entries: {len(entries)})"
                    )
                    embed.set_author(
                        name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
                    )
                    embeds.append(embed)
                    embed = discord.Embed(
                        color=COLORS.neutral, title="Autoresponders", description=""
                    )
                    count = 0

            if count > 0:
                embed.set_footer(
                    text=f"Page {len(embeds) + 1}/{(len(entries) + 4) // 5} (Entries: {len(entries)})"
                )
                embed.set_author(
                    name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
                )
                embeds.append(embed)

            if len(embeds) > 1:
                await ctx.paginate(embeds)
            else:
                await ctx.send(embed=embeds[0])

    @hybrid_group(
        name="boosterrole",
        aliases=["br"],
        description="Configure boosterroles in your guild.",
        invoke_without_command=True,
    )
    async def boosterrole(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    
    @boosterrole.command(
        name="setup",
        aliases=["enable"],
        description="Enable the booster role module in your guild.",
    )
    @commands.has_permissions(manage_guild=True)
    async def boosterrole_setup(self, ctx: Context):
        if await self.bot.pool.fetchrow(
            "SELECT * FROM booster_module WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.warn(
                "The booster role module is already enabled in this guild."
            )

        premium_role = ctx.guild.premium_subscriber_role
        if premium_role is None:
            premium_role = ctx.guild.default_role

        await self.bot.pool.execute(
            "INSERT INTO booster_module (guild_id, base) VALUES ($1, $2)",
            ctx.guild.id,
            premium_role.id,
        )
        return await ctx.approve(f"The booster role module has been enabled.")
    
    @boosterrole.command(
        name="disable", description="Disable the booster role module in your guild."
    )
    @commands.has_permissions(manage_guild=True)
    async def boosterrole_disable(self, ctx: Context):
        await self.bot.pool.execute(
            "DELETE FROM booster_module WHERE guild_id = $1", ctx.guild.id
        )
        await self.bot.pool.execute(
            "DELETE FROM booster_roles WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.approve(f"Disabled the booster role module.")

    @boosterrole.command(name="base", description="Set the base for the booster role.")
    @commands.has_permissions(manage_guild=True)
    async def boosterrole_base(self, ctx: Context, *, role: discord.Role = None):
        check = await self.bot.pool.fetchrow(
            "SELECT base FROM booster_module WHERE guild_id = $1", ctx.guild.id
        )
        if role is None:
            if check is None:
                return await ctx.warn(f"The booster role base role isn't set.")

            await self.bot.pool.execute(
                "UPDATE booster_module SET base = $1 WHERE guild_id = $2",
                None,
                ctx.guild.id,
            )
            return await ctx.approve(f"Removed the booster role base.")

        await self.bot.pool.execute(
            "UPDATE booster_module SET base = $1 WHERE guild_id = $2",
            role.id,
            ctx.guild.id,
        )
        return await ctx.approve(f"Set the booster role base to: {role.mention}")
    
    @boosterrole.command(name="create", description="Create your booster role.")
    @br_enabled()
    async def boosterrole_create(self, ctx: Context, *, name: str = None):
        if not ctx.author.premium_since:
            return await ctx.warn(
                f"You need to boost this server in order to use this command."
            )
        check = await self.bot.pool.fetchrow(
            "SELECT base FROM booster_module WHERE guild_id = $1", ctx.guild.id
        )

        if not name:
            name = f"{ctx.author.name}'s role"

        if await self.bot.pool.fetchrow(
            "SELECT * FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        ):
            return await ctx.warn("You already have a booster role.")

        base = ctx.guild.get_role(check)
        role = await ctx.guild.create_role(
            name=name, reason=f"{ctx.author} created their booster role."
        )
        await role.edit(position=base.position if base is not None else 1)
        await ctx.author.add_roles(role)
        await self.bot.pool.execute(
            "INSERT INTO booster_roles VALUES ($1,$2,$3)",
            ctx.guild.id,
            ctx.author.id,
            role.id,
        )
        return await ctx.approve("Booster role has been created.")

    @boosterrole.command(name="name", description="Rename your boosterrole.")
    @has_br_role()
    async def boosterrole_name(self, ctx: Context, *, name: str):

        if len(name) > 32:
            return await ctx.warn(
                "The booster role name can't be more than **32** characters long."
            )

        role = ctx.guild.get_role(
            await self.bot.pool.fetchval(
                "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                ctx.author.id,
            )
        )
        if not role:
            return await ctx.warn(
                f"You don't have a booster role setup. Use `{ctx.clean_prefix}br create` to create one."
            )

        await role.edit(
            name=name, reason=f"{ctx.author.name} edited their booster role."
        )
        return await ctx.approve(f"Renamed your booster role to **{name}**")
    
    @boosterrole.command(
        name="colour", aliases=["color"], description="Set your booster role's color."
    )
    @has_br_role()
    async def boosterrole_colour(self, ctx: Context, *, color: str):
        if color.startswith("#"):
            color = color[1:]

        try:
            discord_color = discord.Color(int(color, 16))
        except ValueError:
            return await ctx.deny(
                "You need to enter a valid hex code. Example: #47C1BC"
            )

        role = ctx.guild.get_role(
            await self.bot.pool.fetchval(
                "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                ctx.author.id,
            )
        )
        if not role:
            return await ctx.warn(
                f"You don't have a booster role setup. Use `{ctx.clean_prefix}br create` to create one."
            )

        await role.edit(
            color=discord_color, reason=f"{ctx.author} edited their booster role."
        )
        return await ctx.send(
            embed=discord.Embed(
                description=f"{EMOJIS.APPROVE} {ctx.author.mention}: Edited the role's color to {color}",
                color=discord_color,
            )
        )
    
    @boosterrole.command(name="icon", description="Set your booster role icon.")
    @has_br_role()
    @level2()
    async def boosterrole_icon(
        self, ctx: Context, *, icon: discord.PartialEmoji
    ):
        role = ctx.guild.get_role(
            await self.bot.pool.fetchval(
                "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                ctx.author.id,
            )
        )
        if not role:
            return await ctx.warn(
                f"You don't have a booster role setup. Use `{ctx.clean_prefix}br create` to create one."
            )

        await role.edit(
            display_icon=(
                await icon.read() if isinstance(icon, discord.PartialEmoji) else icon
            ),
            reason=f"{ctx.author} edited their booster role",
        )
        return await ctx.approve(
            f"Booster role icon has been set to {icon.name if isinstance(icon, discord.PartialEmoji) else icon}"
        )

    @boosterrole.command(name="delete", description="Delete your booster role.")
    @has_br_role()
    async def boosterrole_delete(self, ctx: Context):
        role = ctx.guild.get_role(
            await self.bot.pool.fetchval(
                "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
                ctx.guild.id,
                ctx.author.id,
            )
        )
        if not role:
            return await ctx.warn(
                f"You don't have a booster role setup. Use `{ctx.clean_prefix}br create` to create one."
            )

        await role.delete(reason=f"{ctx.author} deleted their booster role.")
        await self.bot.pool.execute(
            "DELETE FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        return await ctx.approve(f"Your booster role has been deleted.")
    
    @hybrid_group(
        name="leaves",
        aliases=["bye", "leave", "leaver", "goodbye"],
        description="Configure the leave messages.",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def leaves(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @leaves.command(name="add", aliases=["set"], description="""Add a leave message to a channel.""")
    @has_permissions(manage_messages=True)
    async def leaves_add(self, ctx: Context, channel: TextChannel, *, message: str):

        query = "SELECT 1 FROM leave WHERE channel_id = $1"
        action = "Edited" if await self.bot.pool.fetchrow(query, channel.id) else "Set"

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO leave (guild_id, channel_id, message)
            VALUES (?, ?, ?)
            """,
            ctx.guild.id,
            channel.id,
            message,
        )

        await ctx.approve(f"**{action}** {channel.mention}'s leave message to: ")

        await send_embed(ctx.channel, message, ctx.author)

    @leaves.command(name="remove", aliases=["delete", "rm"], description= """Removes a channel's leave message""")
    @has_permissions(manage_messages=True)
    async def leave_remove(self, ctx: Context, *, channel: TextChannel):
        if await self.bot.pool.fetchrow(
            "SELECT * FROM leave WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            await self.bot.pool.execute(
                "DELETE FROM leave WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )
            return await ctx.approve(
                f"**Removed** the leave configuration from {channel.mention}."
            )
        else:
            return await ctx.warn(f"No **leave messages** found in that channel.")

    @leaves.command(name="test", aliases=["view"], description="""Test a channel's leave message.""")
    @has_permissions(manage_messages=True)
    async def leaves_view(self, ctx: Context, channel: TextChannel = None):  # type: ignore
        if channel is None:
            channel = ctx.channel

        data = await self.bot.pool.fetch(
            "SELECT * FROM leave WHERE guild_id = $1", ctx.guild.id
        )

        for result in data:
            channel = self.bot.get_channel(result["channel_id"])  # type: ignore
            if channel:
                await send_embed(channel, result["message"], ctx.author)
                await ctx.message.add_reaction(f"{EMOJIS.APPROVE}")
                await asyncio.sleep(0.5)

    @leaves.command(name="list")
    @has_permissions(manage_messages=True)
    async def leaves_list(self, ctx: Context):
        """List all leave messages set in the guild."""

        rows = await self.bot.pool.fetch(
            "SELECT channel_id, message FROM leave WHERE guild_id=$1",
            ctx.guild.id,
        )

        if not rows:
            return await ctx.warn("No leave messages are set in this guild.")

        embed = Embed(title="Leave Messages", color=COLORS.neutral)
        for index, row in enumerate(rows, start=1):
            channel = ctx.guild.get_channel(row["channel_id"])
            embed.add_field(
                name=f"`{index}.` {channel.mention if channel else 'Unknown Channel'} (`{channel.id}`)",  # type: ignore
                value="",
                inline=False,
            )

        await ctx.send(embed=embed)

    @leaves.command(
        name="variables", description="Show available variables for leave messages."
    )
    @has_permissions(manage_messages=True)
    async def leaves_variables(self, ctx: Context):
        embed = discord.Embed(
            color=COLORS.neutral,
            title="Leave Variables",
            description="",
        )
        embed.add_field(
            name="User",
            value=(
                "`{user}`, `{user.name}`, `{user.mention}`, `{user.avatar}`, "
                "`{user.discriminator}`, `{user.joined_at}`, `{user.created_at}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Guild",
            value=(
                "`{guild.name}`, `{guild.count}`, `{guild.count.format}`, "
                "`{guild.id}`, `{guild.created_at}`, `{guild.boost_count}`, "
                "`{guild.boost_count.format}`, `{guild.booster_count}`, "
                "`{guild.booster_count.format}`, `{guild.boost_tier}`, "
                "`{guild.vanity}`, `{guild.icon}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Special",
            value="`{invisible}`, `{botcolor}`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @Cog.listener("on_member_remove")
    async def dispatch_leaves(self, member: Member):
        """Dispatches the leave messages."""
        data = await self.bot.pool.fetch(
            "SELECT * FROM leave WHERE guild_id = $1", member.guild.id
        )

        for result in data:
            channel = self.bot.get_channel(result["channel_id"])
            if channel:
                await send_embed(channel, result["message"], member)
                await asyncio.sleep(0.5)

    @hybrid_group(name="fakeperms", aliases=["fp"], invoke_without_command=True)
    @has_permissions(administrator=True)
    async def fakeperms(self, ctx: Context):
        """Manage fakeperms in your server."""
        return await ctx.send_help(ctx.command)
    
    @fakeperms.command(name="add", aliases=["set"])
    @has_permissions(administrator=True)
    async def fakeperms_add(self, ctx: Context, role: Role, *, permission: str):
        """Add a fakeperm to a role"""
        permission = permission.lower().replace(" ", "_")
        if permission not in self.valid_perms:
            return await ctx.warn(
                f"`{permission}` is not a valid **permission**. Do `{ctx.clean_prefix}fakeperms perms` to view all valid permissions."
            )

        updated_perms = ",".join(
            set(
                (
                    await self.bot.pool.fetchval(
                        "SELECT permission FROM fake_permissions WHERE guild_id = $1 AND role_id = $2",
                        ctx.guild.id,
                        role.id,
                    )
                    or ""
                ).split(",")
            )
            | {permission}
        )

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO fake_permissions (guild_id, role_id, permission)
            VALUES (?, ?, ?)
            """,
            ctx.guild.id,
            role.id,
            updated_perms,
        )

        return await ctx.approve(
            f"`{permission}` has been **assigned** to {role.mention}"
        )
    
    @fakeperms.command(name="list")
    @has_permissions(administrator=True)
    async def fakeperms_list(self, ctx: Context, role: Role):
        """List all fake permissions for a role"""

        permissions = await self.bot.pool.fetchval(
            "SELECT permission FROM fake_permissions WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )

        if not permissions:
            return await ctx.warn(f"No fake permissions found for {role.mention}.")

        permissions = permissions.split(",")
        pages = [permissions[i : i + 10] for i in range(0, len(permissions), 10)]

        embeds = [
            Embed(
                color=COLORS.neutral,
                title=f"Fake Permissions for {role.name}",
                description="\n".join(
                    [f"{i+1}. {perm}" for i, perm in enumerate(page)]
                ),
            )
            .set_author(
                name=ctx.author.name,
                icon_url=ctx.author.display_avatar.url,
            )
            .set_footer(text=f"Page {i + 1}/{len(pages)}")
            for i, page in enumerate(pages)
        ]

        await ctx.paginate(embeds)

    @fakeperms.command(name="remove")
    @has_permissions(administrator=True)
    async def fakeperms_remove(self, ctx: Context, role: Role, *, permission: str):
        permission = permission.lower().replace(" ", "_")
        if permission not in self.valid_perms:
            return await ctx.warn(
                f"`{permission}` is not a valid **permission**. Do `{ctx.clean_prefix}fakeperms perms` to view all valid permissions."
            )

        current_perms = await self.bot.pool.fetchval(
            "SELECT permission FROM fake_permissions WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )

        if not current_perms or permission not in current_perms.split(","):
            return await ctx.warn(
                f"{role.mention} does not have `{permission}` permission."
            )

        updated_perms = ",".join(
            perm for perm in current_perms.split(",") if perm != permission
        )

        await self.bot.pool.execute(
            """
            INSERT OR REPLACE INTO fake_permissions (guild_id, role_id, permission)
            VALUES (?, ?, ?)
            """,
            ctx.guild.id,
            role.id,
            updated_perms,
        )

        return await ctx.approve(
            f"`{permission}` has been **removed** from {role.mention}"
        )
    
    @fakeperms.command(name="perms")
    @has_permissions(administrator=True)
    async def fakeperms_perms(self, ctx: Context):
        permissions = list(self.valid_perms)
        pages = [permissions[i : i + 15] for i in range(0, len(permissions), 15)]

        embeds = []
        current_number = 1

        for i, page in enumerate(pages):
            embed = (
                Embed(
                    color=COLORS.neutral,
                    title="Valid Permissions",
                    description="\n".join(
                        [f"{current_number + j}. {perm}" for j, perm in enumerate(page)]
                    ),
                )
                .set_author(
                    name=ctx.author.name,
                    icon_url=ctx.author.display_avatar.url,
                )
                .set_footer(text=f"Page {i + 1}/{len(pages)}")
            )
            embeds.append(embed)
            current_number += len(page)

        await ctx.paginate(embeds)