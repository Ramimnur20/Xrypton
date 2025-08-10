from __future__ import annotations

from base.config import *
from base.managers.paginator import *
from discord.ext.commands import HelpCommand, Group
from datetime import datetime
from xxhash import xxh32_hexdigest

from discord.ext.commands import Command, Group


from typing import Union
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Unpack, TypedDict, cast

from discord import (
    AllowedMentions,
    ButtonStyle,
    Color,
    Message,
    MessageReference,
    Embed,
    Role,
    Member,
    ui,
)
from discord.ui import View, Button
from discord.ui import button
from discord.ext.commands import Context as BaseContext
from base.config import *

if TYPE_CHECKING:
    from base.bleed import Bot


class FieldDict(TypedDict, total=False):
    name: str
    value: str
    inline: bool


class FooterDict(TypedDict, total=False):
    text: Optional[str]
    icon_url: Optional[str]


class AuthorDict(TypedDict, total=False):
    name: Optional[str]
    icon_url: Optional[str]


class ButtonDict(TypedDict, total=False):
    url: Optional[str]
    emoji: Optional[str]
    style: Optional[ButtonStyle]
    label: Optional[str]


class MessageKwargs(TypedDict, total=False):
    content: Optional[str]
    tts: Optional[bool]
    allowed_mentions: Optional[AllowedMentions]
    reference: Optional[MessageReference]
    mention_author: Optional[bool]
    delete_after: Optional[float]

    # Embed Related
    url: Optional[str]
    title: Optional[str]
    color: Optional[Color]
    image: Optional[str]
    description: Optional[str]
    thumbnail: Optional[str]
    footer: Optional[FooterDict]
    author: Optional[AuthorDict]
    fields: Optional[List[FieldDict]]
    timestamp: Optional[datetime]
    view: Optional[View]
    buttons: Optional[List[ButtonDict]]


class Context(BaseContext):
    bot: "Bot"

    def is_dangerous(self, role: Role) -> bool:
        permissions = role.permissions

        return any(
            [
                permissions.kick_members,
                permissions.ban_members,
                permissions.administrator,
                permissions.manage_channels,
                permissions.manage_guild,
                permissions.manage_messages,
                permissions.manage_roles,
                permissions.manage_webhooks,
                permissions.manage_emojis_and_stickers,
                permissions.manage_threads,
                permissions.mention_everyone,
                permissions.moderate_members,
            ]
        )

    async def embed(self, **kwargs: Unpack[MessageKwargs]) -> Message:
        return await self.send(**self.create(**kwargs))

    def create(self, **kwargs: Unpack[MessageKwargs]) -> Dict[str, Any]:
        """Create a message with the given keword arguments.

        Returns:
            Dict[str, Any]: The message content, embed, view and delete_after.
        """
        view = View()

        for button in kwargs.get("buttons") or []:
            if not button or not button.get("label"):
                continue

            view.add_item(
                Button(
                    label=button.get("label"),
                    style=button.get("style") or ButtonStyle.secondary,
                    emoji=button.get("emoji"),
                    url=button.get("url"),
                )
            )

        embed = (
            Embed(
                url=kwargs.get("url"),
                description=kwargs.get("description"),
                title=kwargs.get("title"),
                color=kwargs.get("color") or COLORS.neutral,
                timestamp=kwargs.get("timestamp"),
            )
            .set_image(url=kwargs.get("image"))
            .set_thumbnail(url=kwargs.get("thumbnail"))
            .set_footer(
                text=cast(dict, kwargs.get("footer", {})).get("text"),
                icon_url=cast(dict, kwargs.get("footer", {})).get("icon_url"),
            )
            .set_author(
                name=cast(dict, kwargs.get("author", {})).get("name", ""),
                icon_url=cast(dict, kwargs.get("author", {})).get("icon_url", ""),
            )
        )

        for field in kwargs.get("fields") or []:
            if not field:
                continue

            embed.add_field(
                name=field.get("name"),
                value=field.get("value"),
                inline=field.get("inline", False),
            )

        return {
            "content": kwargs.get("content"),
            "embed": embed,
            "view": kwargs.get("view") or view,
            "delete_after": kwargs.get("delete_after"),
        }

    async def approve(self, message: str, **kwargs) -> Message:
        return await self.send(
            embed=Embed(
                color=COLORS.approve,
                description=f"{EMOJIS.APPROVE} {self.author.mention}: {message}",
            ),
            **kwargs,
        )

    async def warn(self, message: str, **kwargs) -> Message:
        return await self.send(
            embed=Embed(
                color=COLORS.warn,
                description=f"{EMOJIS.WARN} {self.author.mention}: {message}",
            ),
            **kwargs,
        )

    async def deny(self, message: str, **kwargs) -> Message:
        return await self.send(
            embed=Embed(
                color=COLORS.deny,
                description=f"{EMOJIS.DENY} {self.author.mention}: {message}",
            ),
            **kwargs,
        )

    async def cooldown(self, message: str, **kwargs) -> Message:
        return await self.send(
            embed=Embed(
                color=0x38A9E1,
                description=f"{EMOJIS.COOLDOWN} {self.author.mention}: {message}",
            )
        )

    async def paginate(self, embeds: List[discord.Embed], **kwargs) -> Message:
        if len(embeds) == 1:
            if isinstance(embeds[0], discord.Embed):
                return await self.send(embed=embeds[0])

        return await self.send(embed=embeds[0], view=Paginator(self, embeds), **kwargs)


class BleedHelp(HelpCommand):
    context: "Context"

    def __init__(self, **options):
        super().__init__(
            command_attrs={"aliases": ["h", "cmds", "commands"], "hidden": True},
            verify_checks=False,
            **options,
        )

    async def send_bot_help(self, mapping):
        commands_list = []
        for command_list in mapping.values():
            commands_list.extend(command_list)

        command_names = ', '.join(f"`{cmd.qualified_name}`" for cmd in commands_list if not cmd.hidden)
        
        await self.context.reply(f"{command_names}")

    async def send_command_help(self, command: Command):
        aliases = command.aliases

        try:
            permissions = command.permissions  # type: ignore
        except (AttributeError, TypeError):
            permissions = []

        embed = (
            Embed(
                color=COLORS.neutral,
                title=f"Command: {command.qualified_name}",
                description=command.help or "No description provided",
            )
            .set_author(
                name=self.context.author.name,
                icon_url=self.context.author.display_avatar.url,
            )
            .add_field(
                name="Aliases",
                value=", ".join(aliases) if aliases else "N/A",
                inline=True,
            )
            .add_field(
                name="Parameters",
                value=(
                    ", ".join(command.clean_params) if command.clean_params else "N/A"
                ),
                inline=True,
            )
            .add_field(
                name="Information",
                value=f"{EMOJIS.WARN} "
                + (", ".join(permissions) if permissions else "N/A"),
                inline=True,
            )
            .add_field(
                name="Usage",
                value=f"```Syntax: {command.qualified_name} {command.usage or ''}```",
                inline=False,
            )
            .set_footer(
                text=(
                    f"Page 1/1 • Module: " + command.cog_name.lower()
                    if command.cog_name
                    else "N/A"
                ),
            )
        )
        return await self.context.send(embed=embed)
    
    async def send_group_help(self, group: Group):
        embeds = []

        group_permissions = set()
        for cmd in group.commands:
            try:
                if hasattr(cmd, "permissions") and cmd.permissions:  # type: ignore
                    group_permissions.update(cmd.permissions)  # type: ignore
            except (AttributeError, TypeError):
                continue
        
        group_embed = (
            Embed(
                color=COLORS.neutral,
                title=f"Command Group: {group.name}",
                description=group.help or "No description provided",
            )
            .set_author(
                name=self.context.author.name,
                icon_url=self.context.author.display_avatar.url,
            )
            .add_field(
                name="Aliases",
                value=", ".join(group.aliases) if group.aliases else "N/A",
                inline=True,
            )
            .add_field(
                name="Parameters",
                value=", ".join(group.clean_params) if group.clean_params else "N/A",
                inline=True,
            )
            .add_field(
                name="Information",
                value=f"{EMOJIS.WARN} "
                + (", ".join(group_permissions) if group_permissions else "N/A"),
                inline=True,
            )
            .add_field(
                name="Usage",
                value=f"```Syntax: {group.qualified_name} {group.usage or ''}```",
                inline=False,
            )
            .set_footer(
                text=f"Page 1/{len(group.commands) + 1} • Module: {group.cog_name.lower() if group.cog_name else 'N/A'}"
            )
        )
        embeds.append(group_embed)

        for i, command in enumerate(group.commands):
            try:
                permissions = command.permissions  # type: ignore
            except (AttributeError, TypeError):
                permissions = []

            command_embed = (
                Embed(
                    color=COLORS.neutral,
                    title=f"Command: {command.name}",
                    description=command.help or "No description provided",
                )
                .set_author(
                    name=self.context.author.name,
                    icon_url=self.context.author.display_avatar.url,
                )
                .add_field(
                    name="Aliases",
                    value=", ".join(command.aliases) if command.aliases else "N/A",
                    inline=True,
                )
                .add_field(
                    name="Parameters",
                    value=(
                        ", ".join(command.clean_params)
                        if command.clean_params
                        else "N/A"
                    ),
                    inline=True,
                )
                .add_field(
                    name="Information",
                    value=f"{EMOJIS.WARN} "
                    + (", ".join(permissions) if permissions else "N/A"),
                    inline=True,
                )
                .add_field(
                    name="Usage",
                    value=f"```Syntax: {command.qualified_name} {command.usage or ''}```",
                    inline=False,
                )
                .set_footer(
                    text=f"Page {i + 2}/{len(group.commands) + 1} • Module: {command.cog_name.lower() if command.cog_name else 'N/A'}"
                )
            )

            embeds.append(command_embed)
        await self.context.paginate(embeds)



class Confirmation(View):
    def __init__(self, ctx: Context, user: Member, reason: str, action: str):
        super().__init__()
        self.ctx = ctx
        self.user = user
        self.reason = reason
        self.action = action
        self.message = None

    async def send_confirmation(self):
        embed = Embed(
            title="",
            description=f"Are you sure you want to {self.action} {self.user.mention if self.user else ''}?",
            color=COLORS.neutral,
        )
        self.message = await self.ctx.send(embed=embed, view=self)

    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes_button(self, button: Button, interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message(
                "You cannot confirm this action.", ephemeral=True
            )
            return
        if self.action == "ban" and self.user:
            await self.user.ban(reason=self.reason)
            await self.ctx.approve(f"{self.user.mention} has been **banned**.")
        elif self.action == "kick" and self.user:
            await self.user.kick(reason=self.reason)
            await self.ctx.approve(f"{self.user.mention} has been **kicked**.")

        if self.message:
            await self.message.delete()
        self.stop()

    @ui.button(label="No", style=discord.ButtonStyle.red)
    async def no_button(self, button: Button, interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message(
                "You cannot confirm cancel action.", ephemeral=True
            )
            return
        await self.ctx.approve(
            f"{self.action.capitalize()} action has been **cancelled**."
        )
        if self.message:
            await self.message.delete()
        self.stop()
