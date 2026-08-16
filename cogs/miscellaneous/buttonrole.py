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


class EditorView(View):
    def __init__(self, cog: "ButtonRole", ctx: Context):
        super().__init__(timeout=600)
        self.cog = cog
        self.ctx = ctx
        self.message: Optional[Message] = None
        self.state: Dict[str, Any] = {
            "message": None,
            "channel": None,
            "style": None,
            "label": None,
            "role": None,
            "emoji": None,
        }

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: This editor session belongs to {self.ctx.author.mention}.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return False
        return True

    def build_embed(self) -> Embed:
        msg = self.state["message"]
        style = self.state["style"]
        label = self.state["label"]
        role = self.state["role"]
        emoji = self.state["emoji"]

        msg_str = f"✅ [Jump to Message]({msg.jump_url})" if msg else "⬜ *Not set*"
        style_str = f"✅ **{style.capitalize()}**" if style else "⬜ *Not set*"
        label_str = f"✅ **{label}**" if label else "⬜ *Not set*"
        role_str = f"✅ {role.mention}" if role else "⬜ *Not set*"
        emoji_str = f"✅ {emoji}" if emoji else "⬜ *None (optional)*"

        embed = Embed(
            title="Button Role — Interactive Editor",
            description=(
                "Use the buttons below to configure your button role. "
                "Once all required fields are set, click **Done** to attach the button to your message.\n\n"
                f"**Target Message:** {msg_str}\n"
                f"**Button Style:** {style_str}\n"
                f"**Button Label:** {label_str}\n"
                f"**Role Assignment:** {role_str}\n"
                f"**Emoji Icon:** {emoji_str}"
            ),
            color=COLORS.neutral,
        )
        embed.set_footer(text="Interactive Editor • Times out after 10 minutes of inactivity")
        return embed

    async def update_message(self):
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    @discord.ui.button(label="Message Link or ID", style=ButtonStyle.primary, row=0, custom_id="editor:msg_btn")
    async def set_message(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditorMessageModal(self))

    @discord.ui.button(label="Style", style=ButtonStyle.primary, row=0, custom_id="editor:style_btn")
    async def set_style(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "Select the button style (color):",
            view=EditorStyleSelectView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="Label", style=ButtonStyle.primary, row=0, custom_id="editor:label_btn")
    async def set_label(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditorLabelModal(self))

    @discord.ui.button(label="Role Assignment", style=ButtonStyle.primary, row=1, custom_id="editor:role_btn")
    async def set_role(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "Select the role to assign/remove on click:",
            view=EditorRoleSelectView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="Done", style=ButtonStyle.success, row=1, custom_id="editor:done_btn")
    async def finish(self, interaction: discord.Interaction, button: Button):
        missing = []
        if not self.state["message"]:
            missing.append("Target Message")
        if not self.state["style"]:
            missing.append("Button Style")
        if not self.state["label"]:
            missing.append("Button Label")
        if not self.state["role"]:
            missing.append("Role Assignment")

        if missing:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: Please complete all required fields before finishing:\n" + "\n".join(f"• **{m}**" for m in missing),
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        success, err = await self.cog.create_button_role(
            guild=self.ctx.guild,
            channel=self.state["channel"],
            message=self.state["message"],
            role=self.state["role"],
            style_str=self.state["style"],
            label=self.state["label"],
            emoji_str=self.state["emoji"],
            author_id=self.ctx.author.id,
        )

        if not success:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {interaction.user.mention}: {err}",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        for child in self.children:
            child.disabled = True

        success_embed = Embed(
            title="Button Role Created",
            description=(
                f"{EMOJIS.APPROVE} Successfully created button role!\n\n"
                f"• **Button:** {self.state['label']}\n"
                f"• **Role:** {self.state['role'].mention}\n"
                f"• **Style:** `{self.state['style']}`\n"
                f"• **Target:** [Jump to Message]({self.state['message'].jump_url})"
            ),
            color=COLORS.approve,
        )
        await interaction.response.edit_message(embed=success_embed, view=None)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                timeout_embed = Embed(
                    description=f"{EMOJIS.WARN} Editor session expired. Run `,buttonrole editor` to start a new session.",
                    color=COLORS.warn,
                )
                await self.message.edit(embed=timeout_embed, view=None)
            except (discord.NotFound, discord.HTTPException):
                pass


class HomeView(View):
    def __init__(self, cog: "ButtonRole", ctx: Context):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.message: Optional[Message] = None

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

    @discord.ui.button(label="Create New", style=ButtonStyle.success, emoji="➕", custom_id="home:create_new")
    async def create_new(self, interaction: discord.Interaction, button: Button):
        editor = EditorView(self.cog, self.ctx)
        embed = editor.build_embed()
        await interaction.response.send_message(embed=embed, view=editor)
        editor.message = await interaction.original_response()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


class ButtonRole(CogMeta):
    """Button Role system allowing staff to attach persistent role-assignment buttons to messages."""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self._cooldowns: Dict[Tuple[int, int], float] = {}

    async def cog_load(self):
        await self.ensure_schema()
        await self._register_persistent_views()

    async def ensure_schema(self):
        query = """
        CREATE TABLE IF NOT EXISTS button_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            style TEXT NOT NULL,
            emoji TEXT,
            custom_id TEXT NOT NULL UNIQUE,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL
        );
        """
        await self.bot.pool.execute(query)

    async def _register_persistent_views(self):
        """Query every distinct message with button roles on startup and register persistent views."""
        rows = await self.bot.pool.fetch(
            "SELECT DISTINCT guild_id, channel_id, message_id FROM button_roles"
        )
        count = 0
        for row in rows:
            view = await self.build_view_for_message(row["message_id"])
            if view and len(view.children) > 0:
                self.bot.add_view(view)
                count += 1
        logger.info(f"ButtonRole | Registered {count} persistent views on startup.")

    async def build_view_for_message(self, message_id: int) -> Optional[View]:
        """Shared helper to build a persistent discord.ui.View for a given message ID."""
        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            message_id,
        )
        if not rows:
            return None

        view = View(timeout=None)
        for i, row in enumerate(rows[:25]):
            row_idx = i // 5
            view.add_item(ButtonRoleButton(self, row, row_idx=row_idx))
        return view

    async def handle_button_click(self, interaction: discord.Interaction, row: dict):
        """Handle live button role clicks with toggle behavior, cooldowns, and error handling."""
        if not interaction.guild or not isinstance(interaction.user, Member):
            return

        user: Member = interaction.user
        guild = interaction.guild
        button_id = row["id"]

        # 1. Cooldown check (2.5 seconds per-user per-button)
        cd_key = (user.id, button_id)
        now = time.time()
        last_clicked = self._cooldowns.get(cd_key, 0.0)
        if now - last_clicked < 2.5:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.COOLDOWN} {user.mention}: You're clicking too fast! Please wait a moment.",
                    color=COLORS.neutral,
                ),
                ephemeral=True,
            )
            return
        self._cooldowns[cd_key] = now

        # 2. Check if the underlying role still exists in the guild
        role = guild.get_role(row["role_id"])
        if not role:
            logger.warning(
                f"ButtonRole | Role ID {row['role_id']} deleted from guild {guild.id}. Deleting stale button role {button_id}."
            )
            await self.bot.pool.execute("DELETE FROM button_roles WHERE id = $1", button_id)
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {user.mention}: The role associated with this button no longer exists in this server.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        # 3. Check bot permissions and hierarchy
        if not guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {user.mention}: I am missing the **Manage Roles** permission to give you this role.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        if role >= guild.me.top_role:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {user.mention}: I cannot assign {role.mention} because it sits higher than or equal to my highest role.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
            return

        # 4. Toggle behavior
        try:
            if role in user.roles:
                await user.remove_roles(role, reason=f"Button Role: {row['label']} toggle")
                await interaction.response.send_message(
                    embed=Embed(
                        description=f"{EMOJIS.APPROVE} {user.mention}: Removed the **{role.name}** role.",
                        color=COLORS.approve,
                    ),
                    ephemeral=True,
                )
            else:
                await user.add_roles(role, reason=f"Button Role: {row['label']} toggle")
                await interaction.response.send_message(
                    embed=Embed(
                        description=f"{EMOJIS.APPROVE} {user.mention}: Gave you the **{role.name}** role.",
                        color=COLORS.approve,
                    ),
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.DENY} {user.mention}: I do not have permission to modify your roles.",
                    color=COLORS.deny,
                ),
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.error(f"ButtonRole | Error toggling role {role.id} for user {user.id}: {e}")
            await interaction.response.send_message(
                embed=Embed(
                    description=f"{EMOJIS.WARN} {user.mention}: An error occurred while updating your roles. Please try again later.",
                    color=COLORS.warn,
                ),
                ephemeral=True,
            )


    async def resolve_message(
        self,
        guild: discord.Guild,
        current_channel: discord.abc.Messageable,
        input_str: str,
    ) -> Tuple[Optional[Message], Optional[str]]:
        """Resolve a jump URL or raw message ID into a discord.Message."""
        if not input_str:
            return None, "No message link or ID provided."

        input_str = input_str.strip()

        # Match Discord jump URL format
        match = re.match(
            r"^https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)$",
            input_str,
        )
        if match:
            g_id, c_id, m_id = map(int, match.groups())
            if g_id != guild.id:
                return None, "That message link belongs to a different server."

            channel = guild.get_channel(c_id)
            if not channel or not isinstance(channel, (TextChannel, discord.Thread, discord.VoiceChannel)):
                try:
                    channel = await self.bot.fetch_channel(c_id)
                except Exception:
                    return None, "Could not access the channel for that message link."

            try:
                msg = await channel.fetch_message(m_id)
                return msg, None
            except discord.NotFound:
                return None, "Message not found in that channel."
            except discord.Forbidden:
                return None, "I do not have permission to read messages in that channel."
            except Exception as e:
                return None, f"Failed to fetch message: {e}"

        # Match raw message ID (only resolves within the invoking channel)
        if input_str.isdigit():
            m_id = int(input_str)
            if hasattr(current_channel, "fetch_message"):
                try:
                    msg = await current_channel.fetch_message(m_id)
                    return msg, None
                except discord.NotFound:
                    return None, "Message not found in this channel. For messages in other channels, provide the full message link."
                except discord.Forbidden:
                    return None, "I do not have permission to view that message."
                except Exception as e:
                    return None, f"Failed to fetch message: {e}"
            return None, "Cannot fetch messages in this channel type."

        return None, "Invalid message format. Provide a full message jump URL or a message ID."

    async def resolve_role(self, guild: discord.Guild, role_str: str) -> Optional[Role]:
        """Resolve a role mention, ID, or name into a discord.Role."""
        if not role_str:
            return None

        role_str = role_str.strip()

        # Mention: <@&123456>
        mention_match = re.match(r"^<@&(\d+)>$", role_str)
        if mention_match:
            return guild.get_role(int(mention_match.group(1)))

        # Raw ID
        if role_str.isdigit():
            role = guild.get_role(int(role_str))
            if role:
                return role

        # Name lookup (case-insensitive)
        for r in guild.roles:
            if r.name.lower() == role_str.lower():
                return r

        return None

    def validate_role(self, guild: discord.Guild, role: Role) -> Optional[str]:
        """Validate if a role can be used as a self-assignable button role."""
        if role == guild.default_role:
            return "You cannot use the `@everyone` role as a button role."
        if role.managed:
            return "That role is managed by an integration or bot and cannot be assigned."
        if guild.me and role >= guild.me.top_role:
            return "That role is higher than or equal to my highest role. Please move my role above it in the server role list."
        return None

    async def create_button_role(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        message: Message,
        role: Role,
        style_str: str,
        label: str,
        emoji_str: Optional[str],
        author_id: int,
    ) -> Tuple[bool, str]:
        """Shared logic to validate and attach a new button role to a message."""
        if message.author.id != self.bot.user.id:
            return False, "Buttons can only be attached to messages sent by the bot."

        norm_style = normalize_style(style_str)
        if not norm_style:
            return False, f"Invalid style `{style_str}`. Valid styles are: `danger`, `success`, `primary`, `secondary`."

        role_err = self.validate_role(guild, role)
        if role_err:
            return False, role_err

        if not label or len(label) > 80:
            return False, "Label must be between 1 and 80 characters."

        # Check Discord component limit (max 25 buttons per message)
        count = await self.bot.pool.fetchval(
            "SELECT COUNT(*) FROM button_roles WHERE message_id = $1", message.id
        )
        if count and count >= 25:
            return False, "This message already has the maximum limit of 25 buttons (5 rows of 5)."

        cleaned_emoji = serialize_emoji_input(emoji_str)
        now = datetime.now(timezone.utc)

        # Insert row and get auto-incremented ID
        async with self.bot.pool.acquire() as conn:
            cursor = await conn.db.execute(
                """
                INSERT INTO button_roles (
                    guild_id, channel_id, message_id, role_id, label, style, emoji, custom_id, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild.id,
                    channel.id,
                    message.id,
                    role.id,
                    label,
                    norm_style,
                    cleaned_emoji,
                    f"temp:{int(now.timestamp())}:{message.id}:{role.id}",
                    author_id,
                    now,
                ),
            )
            row_id = cursor.lastrowid
            custom_id = f"buttonrole:{row_id}"
            await conn.db.execute(
                "UPDATE button_roles SET custom_id = ? WHERE id = ?",
                (custom_id, row_id),
            )

        # Rebuild view and edit target message
        view = await self.build_view_for_message(message.id)
        if view:
            try:
                await message.edit(view=view)
                self.bot.add_view(view)
            except discord.Forbidden:
                return False, "I do not have permission to edit that message."
            except discord.HTTPException as e:
                return False, f"Failed to edit target message: {e}"

        return True, "Button role successfully created."

    async def rerender_message(self, guild_id: int, channel_id: int, message_id: int) -> bool:
        """Helper to re-render and edit live message after add/edit/remove mutation."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False
        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return False

        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            return False

        view = await self.build_view_for_message(message_id)
        try:
            if view and len(view.children) > 0:
                await message.edit(view=view)
                self.bot.add_view(view)
            else:
                await message.edit(view=None)
            return True
        except Exception as e:
            logger.error(f"ButtonRole | Failed to re-render message {message_id}: {e}")
            return False


    @example(",buttonrole")
    @group(name="buttonrole", aliases=["br"], invoke_without_command=True)
    @has_permissions(manage_roles=True)
    async def buttonrole(self, ctx: Context):
        """Manage self-assignable button roles on bot messages."""
        embed = Embed(
            title="🔘 Button Role Management",
            description=(
                "Attach persistent, interactive role assignment buttons to any message sent by the bot.\n\n"
                "**Commands:**\n"
                "`•` `,buttonrole editor` — Launch the interactive setup editor\n"
                "`•` `,buttonrole add <message> <role> <style> <label> [emoji]` — Add a button role\n"
                "`•` `,buttonrole remove <message>` — Remove a button role from a message\n"
                "`•` `,buttonrole list` — List all active button roles in the server\n"
                "`•` `,buttonrole edit label <message> <new label>` — Change a button's label\n"
                "`•` `,buttonrole edit role <message> <new role>` — Change a button's assigned role\n"
                "`•` `,buttonrole edit style <message> <new style>` — Change a button's color/style\n"
                "`•` `,buttonrole edit emoji <message> <new emoji>` — Change or remove a button's emoji\n\n"
                "**Styles:** `primary` (blurple), `secondary` (grey), `success` (green), `danger` (red)\n"
                "Click **Create New** below to start configuring a button role with the interactive wizard."
            ),
            color=COLORS.neutral,
        )
        embed.set_footer(text="Xrypton Button Roles • Buttons persist across bot restarts")
        view = HomeView(self, ctx)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @example(",buttonrole editor")
    @buttonrole.command(name="editor")
    @has_permissions(manage_roles=True)
    async def br_editor(self, ctx: Context):
        """Launch the interactive button role setup editor."""
        editor = EditorView(self, ctx)
        embed = editor.build_embed()
        msg = await ctx.send(embed=embed, view=editor)
        editor.message = msg

    @example(",buttonrole add https://discord.com/channels/... @Member success Verify 🛡️")
    @buttonrole.command(name="add")
    @has_permissions(manage_roles=True)
    async def br_add(
        self,
        ctx: Context,
        message_link: Optional[str] = None,
        role_input: Optional[str] = None,
        style: Optional[str] = None,
        label: Optional[str] = None,
        *,
        emoji: Optional[str] = None,
    ):
        """Add a new button role to an existing bot message."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole add <message_link> <role> <style> <label> [emoji]`\n"
                "**Example:** `,buttonrole add https://discord.com/channels/... @Gamer primary Gamers 🎮`"
            )
        if not role_input:
            return await ctx.deny(
                "Missing required argument: `role`.\n"
                "**Usage:** `,buttonrole add <message_link> <role> <style> <label> [emoji]`\n"
                "**Example:** `,buttonrole add https://discord.com/channels/... @Gamer primary Gamers 🎮`"
            )
        if not style:
            return await ctx.deny(
                "Missing required argument: `style` (one of: `danger`, `success`, `primary`, `secondary`).\n"
                "**Usage:** `,buttonrole add <message_link> <role> <style> <label> [emoji]`"
            )
        if not label:
            return await ctx.deny(
                "Missing required argument: `label`.\n"
                "**Usage:** `,buttonrole add <message_link> <role> <style> <label> [emoji]`\n"
                "**Example:** `,buttonrole add https://discord.com/channels/... @Gamer primary Gamers 🎮`"
            )

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        target_role = await self.resolve_role(ctx.guild, role_input)
        if not target_role:
            return await ctx.deny(f"Could not find any role matching `{role_input}`.")

        success, err = await self.create_button_role(
            guild=ctx.guild,
            channel=target_message.channel,
            message=target_message,
            role=target_role,
            style_str=style,
            label=label,
            emoji_str=emoji,
            author_id=ctx.author.id,
        )

        if not success:
            return await ctx.deny(err)

        emoji_display = f" `{emoji}`" if emoji else ""
        return await ctx.approve(
            f"Successfully added button **{label}**{emoji_display} assigning {target_role.mention} "
            f"to [the message]({target_message.jump_url})."
        )

    @example(",buttonrole remove https://discord.com/channels/...")
    @buttonrole.command(name="remove")
    @has_permissions(manage_roles=True)
    async def br_remove(self, ctx: Context, message_link: Optional[str] = None):
        """Remove a button role from a message."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole remove <message_link>`"
            )

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            target_message.id,
        )
        if not rows:
            return await ctx.warn("That message does not have any button roles attached to it.")

        # If exactly one button role on this message, remove it directly
        if len(rows) == 1:
            row_to_remove = rows[0]
            role = ctx.guild.get_role(row_to_remove["role_id"])
            role_str = role.mention if role else f"Role ID `{row_to_remove['role_id']}`"

            await self.bot.pool.execute("DELETE FROM button_roles WHERE id = $1", row_to_remove["id"])
            await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

            return await ctx.approve(
                f"Removed button **{row_to_remove['label']}** ({role_str}) from [the message]({target_message.jump_url})."
            )

        # If multiple buttons, present disambiguation select menu
        view = ButtonDisambiguationView(ctx, rows, "remove")
        prompt_msg = await ctx.send(
            embed=Embed(
                title="Select Button to Remove",
                description=f"This message has **{len(rows)}** button roles. Choose which one to remove:",
                color=COLORS.neutral,
            ),
            view=view,
        )

        await view.wait()

        if not view.selected_row:
            try:
                await prompt_msg.edit(
                    embed=Embed(
                        description=f"{EMOJIS.WARN} Removal cancelled or timed out.",
                        color=COLORS.warn,
                    ),
                    view=None,
                )
            except Exception:
                pass
            return

        chosen = view.selected_row
        role = ctx.guild.get_role(chosen["role_id"])
        role_str = role.mention if role else f"Role ID `{chosen['role_id']}`"

        await self.bot.pool.execute("DELETE FROM button_roles WHERE id = $1", chosen["id"])
        await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

        try:
            await prompt_msg.edit(
                embed=Embed(
                    description=f"{EMOJIS.APPROVE} Removed button **{chosen['label']}** ({role_str}) from [the message]({target_message.jump_url}).",
                    color=COLORS.approve,
                ),
                view=None,
            )
        except Exception:
            await ctx.approve(
                f"Removed button **{chosen['label']}** ({role_str}) from [the message]({target_message.jump_url})."
            )

    @example(",buttonrole list")
    @buttonrole.command(name="list")
    @has_permissions(manage_roles=True)
    async def br_list(self, ctx: Context):
        """List all configured button roles in the server."""
        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE guild_id = $1 ORDER BY channel_id, message_id, id ASC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("There are no button roles configured in this server.")

        # Group by message_id
        grouped: Dict[int, List[dict]] = {}
        for row in rows:
            grouped.setdefault(row["message_id"], []).append(row)

        entries = []
        for msg_id, btn_rows in grouped.items():
            first = btn_rows[0]
            channel = ctx.guild.get_channel(first["channel_id"])
            channel_str = channel.mention if channel else f"`#{first['channel_id']}`"
            jump_link = f"https://discord.com/channels/{ctx.guild.id}/{first['channel_id']}/{msg_id}"

            btn_lines = []
            for btn in btn_rows:
                role = ctx.guild.get_role(btn["role_id"])
                role_str = role.mention if role else f"Deleted Role (`{btn['role_id']}`)"
                emoji_str = f" {btn['emoji']}" if btn.get("emoji") else ""
                created_ts = int(btn["created_at"].timestamp()) if isinstance(btn["created_at"], datetime) else "N/A"
                time_str = f"<t:{created_ts}:R>" if created_ts != "N/A" else "N/A"

                btn_lines.append(
                    f"  `•` **{btn['label']}**{emoji_str} ➔ {role_str} (`{btn['style']}`) • {time_str}"
                )

            entry_text = f"**[Message in {channel_str}]({jump_link})** (`{len(btn_rows)} buttons`)\n" + "\n".join(btn_lines)
            entries.append(entry_text)

        # Build pages (3 messages per page to keep embeds clean)
        per_page = 3
        embeds = []
        total_pages = (len(entries) + per_page - 1) // per_page

        for page_idx in range(total_pages):
            chunk = entries[page_idx * per_page : page_idx * per_page + per_page]
            embed = Embed(
                title=f"🔘 Button Roles — {ctx.guild.name}",
                description=f"Total: **{len(rows)}** buttons across **{len(grouped)}** messages.\n\n" + "\n\n".join(chunk),
                color=COLORS.neutral,
            )
            embed.set_footer(text=f"Page {page_idx + 1}/{total_pages} • {len(rows)} total buttons")
            embeds.append(embed)

        await ctx.paginate(embeds)


    @buttonrole.group(name="edit", invoke_without_command=True)
    @has_permissions(manage_roles=True)
    async def br_edit(self, ctx: Context):
        """Edit an existing button role's properties."""
        embed = Embed(
            title="🔘 Edit Button Role",
            description=(
                "Modify properties of existing button roles.\n\n"
                "`•` `,buttonrole edit label <message> <new label>` — Change button text\n"
                "`•` `,buttonrole edit role <message> <new role>` — Change assigned role\n"
                "`•` `,buttonrole edit style <message> <new style>` — Change button color/style\n"
                "`•` `,buttonrole edit emoji <message> <new emoji>` — Change or remove button icon\n\n"
                "If the target message has multiple buttons, you will be prompted to choose which button to edit."
            ),
            color=COLORS.neutral,
        )
        return await ctx.send(embed=embed)

    async def _disambiguate_edit_target(
        self,
        ctx: Context,
        message: Message,
        rows: List[dict],
        property_name: str,
    ) -> Optional[dict]:
        """Helper to pick target row when multiple buttons are present on a message."""
        if len(rows) == 1:
            return rows[0]

        view = ButtonDisambiguationView(ctx, rows, f"edit {property_name}")
        prompt_msg = await ctx.send(
            embed=Embed(
                title=f"Select Button to Edit {property_name.capitalize()}",
                description=f"This message has **{len(rows)}** buttons. Select the button you wish to edit:",
                color=COLORS.neutral,
            ),
            view=view,
        )

        await view.wait()

        if not view.selected_row:
            try:
                await prompt_msg.edit(
                    embed=Embed(
                        description=f"{EMOJIS.WARN} Edit operation cancelled or timed out.",
                        color=COLORS.warn,
                    ),
                    view=None,
                )
            except Exception:
                pass
            return None

        try:
            await prompt_msg.delete()
        except Exception:
            pass

        return view.selected_row

    @example(",buttonrole edit label https://discord.com/channels/... New Label")
    @br_edit.command(name="label")
    @has_permissions(manage_roles=True)
    async def br_edit_label(
        self,
        ctx: Context,
        message_link: Optional[str] = None,
        *,
        label: Optional[str] = None,
    ):
        """Change the label text of a button role."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole edit label <message_link> <new_label>`"
            )
        if not label:
            return await ctx.deny(
                "Missing required argument: `label`.\n"
                "**Usage:** `,buttonrole edit label <message_link> <new_label>`"
            )

        if len(label) > 80:
            return await ctx.deny("Button label cannot exceed 80 characters.")

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            target_message.id,
        )
        if not rows:
            return await ctx.warn("That message does not have any button roles attached.")

        target_row = await self._disambiguate_edit_target(ctx, target_message, rows, "label")
        if not target_row:
            return

        old_label = target_row["label"]
        await self.bot.pool.execute(
            "UPDATE button_roles SET label = $1 WHERE id = $2",
            label,
            target_row["id"],
        )
        await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

        return await ctx.approve(
            f"Updated button label from **{old_label}** to **{label}** on [the message]({target_message.jump_url})."
        )

    @example(",buttonrole edit role https://discord.com/channels/... @NewRole")
    @br_edit.command(name="role")
    @has_permissions(manage_roles=True)
    async def br_edit_role(
        self,
        ctx: Context,
        message_link: Optional[str] = None,
        *,
        role_input: Optional[str] = None,
    ):
        """Change the assigned role of a button role."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole edit role <message_link> <new_role>`"
            )
        if not role_input:
            return await ctx.deny(
                "Missing required argument: `new_role`.\n"
                "**Usage:** `,buttonrole edit role <message_link> <new_role>`"
            )

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        target_role = await self.resolve_role(ctx.guild, role_input)
        if not target_role:
            return await ctx.deny(f"Could not find any role matching `{role_input}`.")

        role_err = self.validate_role(ctx.guild, target_role)
        if role_err:
            return await ctx.deny(role_err)

        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            target_message.id,
        )
        if not rows:
            return await ctx.warn("That message does not have any button roles attached.")

        target_row = await self._disambiguate_edit_target(ctx, target_message, rows, "role")
        if not target_row:
            return

        await self.bot.pool.execute(
            "UPDATE button_roles SET role_id = $1 WHERE id = $2",
            target_role.id,
            target_row["id"],
        )
        await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

        return await ctx.approve(
            f"Updated button **{target_row['label']}** assigned role to {target_role.mention} on [the message]({target_message.jump_url})."
        )

    @example(",buttonrole edit style https://discord.com/channels/... success")
    @br_edit.command(name="style")
    @has_permissions(manage_roles=True)
    async def br_edit_style(
        self,
        ctx: Context,
        message_link: Optional[str] = None,
        style: Optional[str] = None,
    ):
        """Change the color/style of a button role."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole edit style <message_link> <new_style>`"
            )
        if not style:
            return await ctx.deny(
                "Missing required argument: `style` (one of: `danger`, `success`, `primary`, `secondary`).\n"
                "**Usage:** `,buttonrole edit style <message_link> <new_style>`"
            )

        norm_style = normalize_style(style)
        if not norm_style:
            return await ctx.deny(
                f"Invalid style `{style}`. Valid styles are: `danger` (red), `success` (green), `primary` (blurple), `secondary` (grey)."
            )

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            target_message.id,
        )
        if not rows:
            return await ctx.warn("That message does not have any button roles attached.")

        target_row = await self._disambiguate_edit_target(ctx, target_message, rows, "style")
        if not target_row:
            return

        await self.bot.pool.execute(
            "UPDATE button_roles SET style = $1 WHERE id = $2",
            norm_style,
            target_row["id"],
        )
        await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

        return await ctx.approve(
            f"Updated style for button **{target_row['label']}** to `{norm_style}` on [the message]({target_message.jump_url})."
        )

    @example(",buttonrole edit emoji https://discord.com/channels/... 🛡️")
    @br_edit.command(name="emoji")
    @has_permissions(manage_roles=True)
    async def br_edit_emoji(
        self,
        ctx: Context,
        message_link: Optional[str] = None,
        *,
        emoji: Optional[str] = None,
    ):
        """Change or remove the emoji of a button role (use 'none' to remove)."""
        if not message_link:
            return await ctx.deny(
                "Missing required argument: `message_link`.\n"
                "**Usage:** `,buttonrole edit emoji <message_link> <emoji|none>`"
            )
        if not emoji:
            return await ctx.deny(
                "Missing required argument: `emoji`.\n"
                "**Usage:** `,buttonrole edit emoji <message_link> <emoji|none>`\n"
                "Pass `none` or `clear` to remove the emoji icon."
            )

        target_message, err = await self.resolve_message(ctx.guild, ctx.channel, message_link)
        if err or not target_message:
            return await ctx.deny(err or "Could not find the specified message.")

        rows = await self.bot.pool.fetch(
            "SELECT * FROM button_roles WHERE message_id = $1 ORDER BY id ASC",
            target_message.id,
        )
        if not rows:
            return await ctx.warn("That message does not have any button roles attached.")

        target_row = await self._disambiguate_edit_target(ctx, target_message, rows, "emoji")
        if not target_row:
            return

        cleaned_emoji = serialize_emoji_input(emoji)

        await self.bot.pool.execute(
            "UPDATE button_roles SET emoji = $1 WHERE id = $2",
            cleaned_emoji,
            target_row["id"],
        )
        await self.rerender_message(ctx.guild.id, target_message.channel.id, target_message.id)

        if cleaned_emoji:
            return await ctx.approve(
                f"Updated emoji for button **{target_row['label']}** to {cleaned_emoji} on [the message]({target_message.jump_url})."
            )
        else:
            return await ctx.approve(
                f"Removed emoji from button **{target_row['label']}** on [the message]({target_message.jump_url})."
            )


async def setup(bot) -> None:
    await bot.add_cog(ButtonRole(bot))
