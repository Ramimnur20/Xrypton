from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

import discord
from discord import ButtonStyle, Embed, Member, Message, PartialEmoji, Role, TextChannel, TextStyle
from discord.ext import commands
from discord.ext.commands import group
from discord.ui import Button, Modal, RoleSelect, Select, TextInput, View
from loguru import logger

from base.config import COLORS, EMOJIS
from base.context import Context
from base.managers.predicates import example, has_permissions
from base.managers.types import CogMeta


STYLE_MAP: Dict[str, ButtonStyle] = {
    "danger": ButtonStyle.danger,
    "red": ButtonStyle.danger,
    "success": ButtonStyle.success,
    "green": ButtonStyle.success,
    "primary": ButtonStyle.primary,
    "blurple": ButtonStyle.primary,
    "secondary": ButtonStyle.secondary,
    "grey": ButtonStyle.secondary,
    "gray": ButtonStyle.secondary,
}

STYLE_NAME_MAP: Dict[str, str] = {
    "danger": "danger",
    "red": "danger",
    "success": "success",
    "green": "success",
    "primary": "primary",
    "blurple": "primary",
    "secondary": "secondary",
    "grey": "secondary",
    "gray": "secondary",
}


def normalize_style(style_input: str) -> Optional[str]:
    """Normalize user style input to one of standard style names."""
    if not style_input:
        return None
    return STYLE_NAME_MAP.get(style_input.strip().lower())


def parse_emoji_obj(emoji_str: Optional[str]) -> Optional[Union[PartialEmoji, str]]:
    """Parse a stored emoji string into a discord PartialEmoji or unicode string."""
    if not emoji_str:
        return None
    emoji_str = emoji_str.strip()
    if not emoji_str:
        return None

    # Check for <a:name:id> or <:name:id>
    custom_match = re.match(r"^<(a?):(\w+):(\d+)>$", emoji_str)
    if custom_match:
        animated, name, emoji_id = custom_match.groups()
        return PartialEmoji(name=name, id=int(emoji_id), animated=bool(animated))

    # Check for name:id format
    if ":" in emoji_str:
        parts = emoji_str.split(":")
        if len(parts) == 2 and parts[1].isdigit():
            return PartialEmoji(name=parts[0], id=int(parts[1]))

    return emoji_str


def serialize_emoji_input(emoji_str: Optional[str]) -> Optional[str]:
    """Validate and serialize user-provided emoji input into a stored string format."""
    if not emoji_str:
        return None
    emoji_str = emoji_str.strip()
    if not emoji_str or emoji_str.lower() in ("none", "null", "remove", "clear"):
        return None

    custom_match = re.match(r"^<(a?):(\w+):(\d+)>$", emoji_str)
    if custom_match:
        animated, name, emoji_id = custom_match.groups()
        prefix = "a:" if animated else ""
        return f"<{prefix}{name}:{emoji_id}>"

    # Unicode emoji or raw string
    return emoji_str


class ButtonRoleButton(Button):
    def __init__(self, cog: "ButtonRole", row: dict, row_idx: int = 0):
        style_enum = STYLE_MAP.get(row["style"], ButtonStyle.secondary)
        parsed_emoji = parse_emoji_obj(row.get("emoji"))
        super().__init__(
            style=style_enum,
            label=row["label"],
            emoji=parsed_emoji,
            custom_id=row["custom_id"],
            row=row_idx,
        )
        self.cog = cog
        self.row_data = row

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_button_click(interaction, self.row_data)


class RemoveConfirmView(View):
    def __init__(self, ctx: Context, label: str):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.label = label
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: This confirmation is not for you.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


class ButtonDisambiguationView(View):
    def __init__(self, ctx: Context, rows: List[dict], action_desc: str):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.rows = rows
        self.selected_row: Optional[dict] = None

        options = []
        for row in rows[:25]:
            role = ctx.guild.get_role(row["role_id"])
            role_name = role.name if role else f"Unknown ({row['role_id']})"
            emoji_str = f" [{row['emoji']}]" if row.get("emoji") else ""
            desc = f"Role: @{role_name} | Style: {row['style']}"
            if len(desc) > 100:
                desc = desc[:97] + "..."
            label = f"{row['label']}{emoji_str}"
            if len(label) > 100:
                label = label[:97] + "..."

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(row["id"]),
                    description=desc,
                )
            )

        self.select = Select(
            placeholder=f"Select a button to {action_desc}...",
            options=options,
            custom_id="disambiguation:select",
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: You cannot interact with this menu.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        for r in self.rows:
            if r["id"] == selected_id:
                self.selected_row = r
                break
        self.stop()
        await interaction.response.defer()


class EditorMessageModal(Modal, title="Button Role — Target Message"):
    def __init__(self, editor_view: "EditorView"):
        super().__init__()
        self.editor_view = editor_view
        self.message_input = TextInput(
            label="Message Link or Message ID",
            placeholder="https://discord.com/channels/... or message ID",
            style=TextStyle.short,
            required=True,
            max_length=200,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        input_val = self.message_input.value.strip()
        msg, err = await self.editor_view.cog.resolve_message(
            self.editor_view.ctx.guild,
            self.editor_view.ctx.channel,
            input_val,
        )
        if err or not msg:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: {err or 'Message not found.'}",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        if msg.author.id != self.editor_view.cog.bot.user.id:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: Target message must be a message sent by the bot.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        self.editor_view.state["message"] = msg
        self.editor_view.state["channel"] = msg.channel
        await self.editor_view.update_message()
        await interaction.response.send_message(
            embed=Embed(
                description=f"{EMOJIS.APPROVE} {interaction.user.mention}: Set target message: [Jump to message]({msg.jump_url})",
                color=COLORS.approve,
            ),
            ephemeral=True,
        )


class EditorLabelModal(Modal, title="Button Role — Label & Emoji"):
    def __init__(self, editor_view: "EditorView"):
        super().__init__()
        self.editor_view = editor_view
        default_label = editor_view.state.get("label") or ""
        default_emoji = editor_view.state.get("emoji") or ""
        self.label_input = TextInput(
            label="Button Label",
            placeholder="e.g. Announcements, Member, Notifications",
            default=default_label,
            style=TextStyle.short,
            required=True,
            max_length=80,
        )
        self.emoji_input = TextInput(
            label="Emoji (Optional)",
            placeholder="e.g. 🔔, :bell:, <:custom:123456>, or leave blank",
            default=default_emoji,
            style=TextStyle.short,
            required=False,
            max_length=100,
        )
        self.add_item(self.label_input)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction):
        label_val = self.label_input.value.strip()
        emoji_val = self.emoji_input.value.strip() or None
        if not label_val:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: Label cannot be empty.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        self.editor_view.state["label"] = label_val
        self.editor_view.state["emoji"] = serialize_emoji_input(emoji_val)
        await self.editor_view.update_message()
        await interaction.response.send_message(
            embed=Embed(
                description=f"{EMOJIS.APPROVE} {interaction.user.mention}: Set label to **{label_val}**" + (f" with emoji {emoji_val}" if emoji_val else ""),
                color=COLORS.approve,
            ),
            ephemeral=True,
        )


class EditorStyleSelectView(View):
    def __init__(self, editor_view: "EditorView"):
        super().__init__(timeout=60)
        self.editor_view = editor_view

        options = [
            discord.SelectOption(label="Primary (Blurple)", value="primary", emoji="🔵", description="Discord blurple accent"),
            discord.SelectOption(label="Secondary (Grey)", value="secondary", emoji="⚪", description="Neutral grey tone"),
            discord.SelectOption(label="Success (Green)", value="success", emoji="🟢", description="Positive green action"),
            discord.SelectOption(label="Danger (Red)", value="danger", emoji="🔴", description="Warning/destructive red"),
        ]
        self.select = Select(
            placeholder="Choose button style...",
            options=options,
            custom_id="editor:style_select",
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        chosen_style = self.select.values[0]
        self.editor_view.state["style"] = chosen_style
        await self.editor_view.update_message()
        await interaction.response.edit_message(
            content=f"✅ Selected style: **{chosen_style}**",
            view=None,
        )


class EditorRoleSelectView(View):
    def __init__(self, editor_view: "EditorView"):
        super().__init__(timeout=60)
        self.editor_view = editor_view

        self.role_select = RoleSelect(
            placeholder="Select a role to assign...",
            min_values=1,
            max_values=1,
            custom_id="editor:role_select",
        )
        self.role_select.callback = self.on_select
        self.add_item(self.role_select)

    async def on_select(self, interaction: discord.Interaction):
        role = self.role_select.values[0]
        err = self.editor_view.cog.validate_role(self.editor_view.ctx.guild, role)
        if err:
            await interaction.response.edit_message(
                content=f"❌ Cannot use {role.mention}: {err}",
                view=None,
            )
            return

        self.editor_view.state["role"] = role
        await self.editor_view.update_message()
        await interaction.response.edit_message(
            content=f"✅ Selected role: {role.mention}",
            view=None,
        )
