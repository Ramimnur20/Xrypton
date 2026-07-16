import asyncio
import os
import json
import discord
from discord.ext import commands
from base.managers.predicates import has_permissions
from typing import Optional

from base.config import *


def get_ticket():
    async def predicate(ctx: commands.Context):
        check = await ctx.bot.pool.fetchrow(
            "SELECT * FROM ticket_open WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id, ctx.channel.id
        )
        return check is not None
    return commands.check(predicate)


async def make_transcript(channel):
    filename = f"{channel.name}.txt"
    with open(filename, "w") as file:
        async for msg in channel.history(oldest_first=True):
            if not msg.author.bot:
                file.write(f"{msg.created_at} - {msg.author.display_name}: {msg.clean_content}\n")
    return filename


class TicketTopic(discord.ui.Modal, title="Add ticket topic"):
    name = discord.ui.TextInput(label="Topic Name", placeholder="The ticket topics name.", required=True, style=discord.TextStyle.short)
    description = discord.ui.TextInput(label="Topic Description", placeholder="The description of the ticket topic.", required=False, max_length=100, style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        check = await interaction.client.pool.fetchrow(
            "SELECT * FROM ticket_button WHERE guild_id = $1 AND topic = $2",
            interaction.guild.id, self.name.value
        )
        if check:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: A topic with the name **{self.name.value}** already exists", color=COLORS.warn),
                ephemeral=True
            )

        existing_count = len(await interaction.client.pool.fetch("SELECT * FROM ticket_button WHERE guild_id = $1", interaction.guild.id))
        await interaction.client.pool.execute(
            "INSERT INTO ticket_button (identifier, guild_id, topic, template) VALUES ($1, $2, $3, $4)",
            f"topic_{interaction.guild.id}_{existing_count}",
            interaction.guild.id, self.name.value, self.description.value
        )

        await interaction.response.send_message(
            embed=discord.Embed(description=f"{EMOJIS.APPROVE} {interaction.user.mention}: Added new ticket topic **{self.name.value}**", color=COLORS.approve),
            ephemeral=True
        )


class CreateTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create", emoji="🎫", style=discord.ButtonStyle.gray, custom_id="persistent_view:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await interaction.client.pool.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", interaction.guild.id)
        if not config:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: Ticket module was disabled", color=COLORS.warn),
                ephemeral=True
            )

        existing = await interaction.client.pool.fetchrow("SELECT * FROM ticket_open WHERE guild_id = $1 AND user_id = $2", interaction.guild.id, interaction.user.id)
        if existing:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: You already have a ticket opened", color=COLORS.warn),
                ephemeral=True
            )

        topics = await interaction.client.pool.fetch("SELECT * FROM ticket_button WHERE guild_id = $1", interaction.guild.id)

        if not topics:
            await self._create_ticket(interaction, config)
        else:
            options = [discord.SelectOption(label=topic["topic"] or "Untitled", description=topic["template"] or "No description", value=topic["topic"] or "untitled") for topic in topics if topic["topic"]]
            if not options:
                await self._create_ticket(interaction, config)
                return

            embed = discord.Embed(description="🔍 Please choose a topic", color=COLORS.neutral)
            select = discord.ui.Select(options=options, placeholder="select a topic...")

            async def select_callback(inte: discord.Interaction):
                await self._create_ticket(inte, config, select.values[0])

            select.callback = select_callback
            view = discord.ui.View()
            view.add_item(select)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _create_ticket(self, interaction: discord.Interaction, config, topic=None):
        button_config = await interaction.client.pool.fetchrow("SELECT category_id FROM ticket_button WHERE guild_id = $1 LIMIT 1", interaction.guild.id)
        category = interaction.guild.get_channel(button_config["category_id"]) if button_config and button_config.get("category_id") else None
        channel_name = config.get("channel_name") or f"ticket-{interaction.user.name}"

        text = await interaction.guild.create_text_channel(
            name=channel_name.replace("{user}", interaction.user.name),
            reason="opened ticket",
            category=category
        )

        overwrites = discord.PermissionOverwrite(send_messages=True, view_channel=True, attach_files=True, embed_links=True)
        await text.set_permissions(interaction.user, overwrite=overwrites)

        overwrite1 = text.overwrites_for(interaction.guild.default_role)
        overwrite1.view_channel = False
        await text.set_permissions(interaction.guild.default_role, overwrite=overwrite1)

        embed = discord.Embed(
            title=topic if topic else "Support Ticket",
            description="Support will be with you shortly, please be patient.\n\nTo close the ticket press the button down below.",
            color=COLORS.neutral
        )

        await interaction.client.pool.execute(
            "INSERT INTO ticket_open (identifier, guild_id, channel_id, user_id) VALUES ($1, $2, $3, $4)",
            f"ticket_{interaction.guild.id}_{text.id}", interaction.guild.id, text.id, interaction.user.id
        )

        if hasattr(interaction, "response") and not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{EMOJIS.APPROVE} {interaction.user.mention}: Opened ticket in {text.mention}", color=COLORS.approve),
                ephemeral=True
            )
        else:
            await interaction.edit_original_response(
                embed=discord.Embed(description=f"{EMOJIS.APPROVE} {interaction.user.mention}: Opened ticket in {text.mention}", color=COLORS.approve),
                view=None
            )

        mes = await text.send(content=f"{interaction.user.mention}, Welcome.", embed=embed, view=DeleteTicket(), allowed_mentions=discord.AllowedMentions.all())

        staff_ids = json.loads(config.get("staff_ids") or "[]")
        for staff_id in staff_ids:
            await text.send(f"<@&{staff_id}>", allowed_mentions=discord.AllowedMentions(roles=True), delete_after=5)

        await mes.pin()


class DeleteTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="", emoji="🗑️", style=discord.ButtonStyle.gray, custom_id="persistent_view:delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.red)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.gray)

        async def close_callback(inte: discord.Interaction):
            logs_channel = await inte.client.pool.fetchval("SELECT logging_channel FROM ticket_config WHERE guild_id = $1", inte.guild.id)

            if logs_channel and logs_channel != 0:
                filename = await make_transcript(interaction.channel)
                embed = discord.Embed(
                    title="ticket logs",
                    description=f"Logs for ticket `{inte.channel.id}` | closed by **{inte.user}**",
                    timestamp=discord.utils.utcnow(),
                    color=COLORS.neutral
                )
                try:
                    await inte.guild.get_channel(logs_channel).send(embed=embed, file=discord.File(filename))
                except Exception:
                    pass
                os.remove(filename)

            await inte.client.pool.execute("DELETE FROM ticket_open WHERE channel_id = $1 AND guild_id = $2", inte.channel.id, inte.guild.id)
            await inte.response.edit_message(content=f"closed by {inte.user.mention}", view=None)
            await asyncio.sleep(2)
            await inte.channel.delete()

        async def cancel_callback(inte: discord.Interaction):
            await inte.response.edit_message(content="Aborting closure...", view=None)

        close.callback = close_callback
        cancel.callback = cancel_callback

        view = discord.ui.View()
        view.add_item(close)
        view.add_item(cancel)
        await interaction.response.send_message("Are you sure you want to close the ticket?", view=view)


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(CreateTicket())
        self.bot.add_view(DeleteTicket())

    async def cog_load(self):
        # None of these tables exist in schema.sql, and Postgres schema-qualified names
        # (ticket.open, ticket.button, ticket.config) don't translate to SQLite, so they're
        # flattened to ticket_open / ticket_button / ticket_config and created here.
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER DEFAULT 0,
                message_id INTEGER DEFAULT 0,
                logging_channel INTEGER DEFAULT 0,
                staff_ids TEXT DEFAULT '[]',
                channel_name TEXT
            )
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_button (
                identifier TEXT PRIMARY KEY,
                guild_id INTEGER,
                topic TEXT,
                template TEXT,
                category_id INTEGER
            )
            """
        )
        await self.bot.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_open (
                identifier TEXT PRIMARY KEY,
                guild_id INTEGER,
                channel_id INTEGER,
                user_id INTEGER
            )
            """
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if isinstance(channel, discord.TextChannel):
            await self.bot.pool.execute("DELETE FROM ticket_open WHERE guild_id = $1 AND channel_id = $2", channel.guild.id, channel.id)

    @commands.group(invoke_without_command=True)
    async def ticket(self, ctx):
        await ctx.send_help(ctx.command)

    @ticket.command()
    @has_permissions(manage_channels=True)
    @get_ticket()
    async def add(self, ctx: commands.Context, *, member: discord.Member):
        overwrites = discord.PermissionOverwrite(send_messages=True, view_channel=True, attach_files=True, embed_links=True)
        await ctx.channel.set_permissions(member, overwrite=overwrites)
        await ctx.approve(f"I have added **{member}** to the ticket.")

    @ticket.command()
    @has_permissions(manage_channels=True)
    @get_ticket()
    async def remove(self, ctx: commands.Context, *, member: discord.Member):
        overwrites = discord.PermissionOverwrite(send_messages=False, view_channel=False, attach_files=False, embed_links=False)
        await ctx.channel.set_permissions(member, overwrite=overwrites)
        await ctx.approve(f"I have removed **{member}** from the ticket.")

    @ticket.command()
    @has_permissions(administrator=True)
    async def topics(self, ctx: commands.Context):
        config = await self.bot.pool.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
        if not config:
            return await ctx.warn("no ticket panel created")

        topics = await self.bot.pool.fetch("SELECT * FROM ticket_button WHERE guild_id = $1", ctx.guild.id)
        embed = discord.Embed(description="🔍 Choose a setting", color=COLORS.neutral)

        button1 = discord.ui.Button(label="add topic", style=discord.ButtonStyle.gray)
        button2 = discord.ui.Button(label="remove topic", style=discord.ButtonStyle.red, disabled=len(topics) == 0)

        async def button1_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message(
                    embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: You are **not** the author of this message.", color=COLORS.warn),
                    ephemeral=True
                )
            await interaction.response.send_modal(TicketTopic())

        async def button2_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return await interaction.response.send_message(
                    embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: You are **not** the author of this message.", color=COLORS.warn),
                    ephemeral=True
                )

            e = discord.Embed(description="🔍 Select a topic to delete.", color=COLORS.neutral)
            options = [discord.SelectOption(label=topic["topic"] or "Untitled", description=topic["template"] or "No description", value=topic["topic"] or "untitled") for topic in topics if topic["topic"]]
            if not options:
                return await interaction.response.send_message(
                    embed=discord.Embed(description=f"{EMOJIS.WARN} {interaction.user.mention}: No valid topics to remove.", color=COLORS.warn),
                    ephemeral=True
                )
            select = discord.ui.Select(options=options, placeholder="Select a topic.")

            async def select_callback(inter: discord.Interaction):
                if inter.user != ctx.author:
                    return await inter.response.send_message(
                        embed=discord.Embed(description=f"{EMOJIS.WARN} {inter.user.mention}: You are **not** the author of this message.", color=COLORS.warn),
                        ephemeral=True
                    )

                await self.bot.pool.execute("DELETE FROM ticket_button WHERE guild_id = $1 AND topic = $2", inter.guild.id, select.values[0])
                await inter.response.send_message(
                    embed=discord.Embed(description=f"{EMOJIS.APPROVE} {inter.user.mention}: I have removed **{select.values[0]}** topic.", color=COLORS.approve),
                    ephemeral=True
                )

            select.callback = select_callback
            v = discord.ui.View()
            v.add_item(select)
            await interaction.response.edit_message(embed=e, view=v)

        button1.callback = button1_callback
        button2.callback = button2_callback

        view = discord.ui.View()
        view.add_item(button1)
        view.add_item(button2)
        await ctx.reply(embed=embed, view=view)

    @ticket.command()
    @has_permissions(administrator=True)
    async def staff(self, ctx: commands.Context, role: Optional[discord.Role] = None):
        if not role:
            await self.bot.pool.execute("UPDATE ticket_config SET staff_ids = '[]' WHERE guild_id = $1", ctx.guild.id)
            return await ctx.approve("I have removed **support roles**.")

        config = await self.bot.pool.fetchrow("SELECT staff_ids FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
        staff_ids = json.loads(config["staff_ids"]) if config and config["staff_ids"] else []

        if role.id in staff_ids:
            staff_ids.remove(role.id)
            await self.bot.pool.execute("UPDATE ticket_config SET staff_ids = $1 WHERE guild_id = $2", json.dumps(staff_ids), ctx.guild.id)
            await ctx.approve(f"I have removed **{role.name}** as a **support role**.")
        else:
            staff_ids.append(role.id)
            await self.bot.pool.execute("UPDATE ticket_config SET staff_ids = $1 WHERE guild_id = $2", json.dumps(staff_ids), ctx.guild.id)
            await ctx.approve(f"I have added **{role.name}** as a **support role**.")

    @ticket.command()
    @has_permissions(administrator=True)
    async def category(self, ctx: commands.Context, channel: Optional[discord.CategoryChannel] = None):
        if channel:
            existing = await self.bot.pool.fetchrow("SELECT identifier FROM ticket_button WHERE guild_id = $1 AND identifier LIKE 'category_%' LIMIT 1", ctx.guild.id)
            if existing:
                await self.bot.pool.execute("UPDATE ticket_button SET category_id = $1 WHERE identifier = $2", channel.id, existing["identifier"])
            else:
                await self.bot.pool.execute(
                    "INSERT INTO ticket_button (identifier, guild_id, category_id) VALUES ($1, $2, $3)",
                    f"category_{ctx.guild.id}", ctx.guild.id, channel.id
                )
            await ctx.approve(f"tickets category set to {channel.mention}")
        else:
            await self.bot.pool.execute("UPDATE ticket_button SET category_id = NULL WHERE guild_id = $1", ctx.guild.id)
            await ctx.approve("I have **removed** tickets category.")

    @ticket.command()
    @has_permissions(administrator=True)
    async def channel(self, ctx: commands.Context, *, channel: Optional[discord.TextChannel] = None):
        if channel:
            await self.bot.pool.execute(
                "INSERT INTO ticket_config (guild_id, channel_id, message_id) VALUES ($1, $2, 0) "
                "ON CONFLICT (guild_id) DO UPDATE SET channel_id = excluded.channel_id",
                ctx.guild.id, channel.id
            )
            await ctx.approve(f"tickets channel set to {channel.mention}")
        else:
            await self.bot.pool.execute("UPDATE ticket_config SET channel_id = 0 WHERE guild_id = $1", ctx.guild.id)
            await ctx.approve("I have **removed** the tickets channel.")

    @ticket.command()
    @has_permissions(administrator=True)
    async def logs(self, ctx: commands.Context, *, channel: Optional[discord.TextChannel] = None):
        if channel:
            existing = await self.bot.pool.fetchrow("SELECT guild_id FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
            if existing:
                await self.bot.pool.execute("UPDATE ticket_config SET logging_channel = $1 WHERE guild_id = $2", channel.id, ctx.guild.id)
            else:
                await self.bot.pool.execute("INSERT INTO ticket_config (guild_id, channel_id, message_id, logging_channel) VALUES ($1, 0, 0, $2)", ctx.guild.id, channel.id)
            await ctx.approve(f"tickets logs set to {channel.mention}")
        else:
            await self.bot.pool.execute("UPDATE ticket_config SET logging_channel = 0 WHERE guild_id = $1", ctx.guild.id)
            await ctx.approve("I have **removed** the tickets logs.")

    @ticket.command()
    @has_permissions(administrator=True)
    async def send(self, ctx: commands.Context):
        config = await self.bot.pool.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
        if not config or not config["channel_id"]:
            return await ctx.warn("You have **not** set a ticket channel.")

        channel = ctx.guild.get_channel(config["channel_id"])
        if not channel:
            return await ctx.warn("I could **not** find that channel.")

        embed = discord.Embed(
            title="Create a ticket",
            description="Click on the button below this message to create a ticket",
            color=COLORS.neutral
        )

        message = await channel.send(embed=embed, view=CreateTicket())
        await self.bot.pool.execute("UPDATE ticket_config SET message_id = $1 WHERE guild_id = $2", message.id, ctx.guild.id)
        await ctx.approve(f"Sent the **ticket** message to {channel.mention}")

    @ticket.command()
    async def settings(self, ctx: commands.Context):
        config = await self.bot.pool.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
        if not config:
            return await ctx.warn("You have **not** created a ticket panel.")

        button_config = await self.bot.pool.fetchrow("SELECT category_id FROM ticket_button WHERE guild_id = $1 LIMIT 1", ctx.guild.id)

        embed = discord.Embed(title="Ticket Settings", description=f"Settings for **{ctx.guild.name}**", color=COLORS.neutral)
        embed.add_field(name="Ticket Channel", value=ctx.guild.get_channel(config["channel_id"]).mention if config.get("channel_id") and ctx.guild.get_channel(config["channel_id"]) else "N/A")
        embed.add_field(name="Logs Channel", value=ctx.guild.get_channel(config["logging_channel"]).mention if config.get("logging_channel") and ctx.guild.get_channel(config["logging_channel"]) else "N/A")
        embed.add_field(name="Category", value=ctx.guild.get_channel(button_config["category_id"]).mention if button_config and button_config.get("category_id") and ctx.guild.get_channel(button_config["category_id"]) else "N/A")
        await ctx.send(embed=embed)