from contextlib import suppress
from discord import Embed, Guild, Interaction, InteractionResponded, InviteTarget, Member, Role, SelectOption, VoiceChannel, WebhookMessage
from discord.ui import Button, Select, View, button
from discord.utils import format_dt

class DisconnectMembers(Select):
    def __init__(self, member: Member) -> None:
        self.member: Member = member
        self.guild: Guild = member.guild
        self.channel: VoiceChannel = member.voice.channel
        super().__init__(
            placeholder="Choose members...",
            min_values=1,
            max_values=len(self.channel.members),
            options=[
                SelectOption(
                    value=str(member.id),
                    label=f"{member} ({member.id})",
                    emoji="👤",
                )
                for member in self.channel.members
            ],
        )

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        disconnected, failed = 0, 0

        for member_id in self.values:
            if member := self.guild.get_member(int(member_id)):
                if member == self.member:
                    failed += 1
                elif not member.voice or member.voice.channel != self.channel:
                    failed += 1
                else:
                    try:
                        await member.move_to(None)
                        disconnected += 1
                    except Exception:
                        failed += 1

        await interaction.followup.send(f"Successfully **disconnected** {disconnected} members (`{failed}` failed)", ephemeral=True)

class TransferOwnership(Select):
    def __init__(self, member: Member) -> None:
        self.member: Member = member
        self.guild: Guild = member.guild
        self.channel: VoiceChannel = member.voice.channel
        super().__init__(
            placeholder="Choose a member...",
            min_values=1,
            max_values=1,
            options=[
                SelectOption(
                    value=str(member.id),
                    label=f"{member} ({member.id})",
                    emoji="👤",
                )
                for member in self.channel.members
                if member != self.member
            ],
        )

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        
        member_id = int(self.values[0])
        new_owner = self.guild.get_member(member_id)
        
        if not new_owner or not new_owner.voice or new_owner.voice.channel != self.channel:
            return await interaction.followup.send("Selected member is not in the voice channel!", ephemeral=True)
        
        await interaction.client.pool.execute(
            "UPDATE channels SET owner_id = $2 WHERE channel_id = $1",
            self.channel.id, new_owner.id
        )
        
        if self.channel.name.endswith("channel"):
            try:
                await self.channel.edit(name=f"{new_owner.display_name}'s channel")
            except Exception:
                pass
        
        await interaction.followup.send(f"**{new_owner}** now has ownership of this channel", ephemeral=True)

class Interface(View):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if not interaction.user.voice:
            await interaction.response.send_message("You're not connected to a **voice channel**", ephemeral=True)
            return False

        elif not (owner_id := await self.bot.pool.fetchval(
            "SELECT owner_id FROM channels WHERE channel_id = $1",
            interaction.user.voice.channel.id
        )):
            await interaction.response.send_message("You're not in a **VoiceMaster** channel!", ephemeral=True)
            return False

        elif interaction.data["custom_id"] == "voicemaster:claim":
            if interaction.user.id == owner_id:
                await interaction.response.send_message("You already have **ownership** of this voice channel!", ephemeral=True)
                return False
            elif owner_id in (member.id for member in interaction.user.voice.channel.members):
                await interaction.response.send_message("You can't claim this **voice channel**, the owner is still active here.", ephemeral=True)
                return False
            return True

        elif interaction.user.id != owner_id:
            await interaction.response.send_message("You don't own a **voice channel**!", ephemeral=True)
            return False

        return True

    @button(emoji="<:lock:1402024761516621897>", custom_id="voicemaster:lock")
    async def lock(self, interaction: Interaction, button: Button) -> None:

        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            connect=False,
            reason=f"VoiceMaster: {interaction.user} locked voice channel"
        )
        await interaction.response.send_message("Your **voice channel** has been locked", ephemeral=True)

    @button(emoji="<:unlock:1402024772799430787>", custom_id="voicemaster:unlock")
    async def unlock(self, interaction: Interaction, button: Button) -> None:

        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            connect=None,
            reason=f"VoiceMaster: {interaction.user} unlocked voice channel"
        )
        await interaction.response.send_message("Your **voice channel** has been unlocked", ephemeral=True)

    @button(emoji="<:ghost:1402024692239569011>", custom_id="voicemaster:ghost")
    async def ghost(self, interaction: Interaction, button: Button) -> None:

        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {interaction.user} made voice channel hidden"
        )
        await interaction.response.send_message("Your **voice channel** has been hidden", ephemeral=True)

    @button(emoji="<:reveal:1402024749986484374>", custom_id="voicemaster:reveal")
    async def reveal(self, interaction: Interaction, button: Button) -> None:

        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {interaction.user} revealed voice channel"
        )
        await interaction.response.send_message("Your **voice channel** has been revealed", ephemeral=True)

    @button(emoji="<:claim:1402024657758060785>", custom_id="voicemaster:claim")
    async def claim(self, interaction: Interaction, button: Button) -> None:

        await self.bot.pool.execute(
            "UPDATE channels SET owner_id = $2 WHERE channel_id = $1",
            interaction.user.voice.channel.id, interaction.user.id
        )
        if interaction.user.voice.channel.name.endswith("channel"):
            try:
                await interaction.user.voice.channel.edit(name=f"{interaction.user.display_name}'s channel")
            except Exception:
                pass
        await interaction.response.send_message("You are now the owner of this **channel**!", ephemeral=True)

    @button(emoji="<:disconnect:1402024681384448181>", custom_id="voicemaster:disconnect")
    async def disconnect(self, interaction: Interaction, button: Button) -> None:

        view = View(timeout=None)
        view.add_item(DisconnectMembers(interaction.user))
        await interaction.response.send_message("Select members from the **dropdown** to disconnect.", view=view, ephemeral=True)

    @button(emoji="<:crown:1402075744565461042>", custom_id="voicemaster:transfer")
    async def transfer(self, interaction: Interaction, button: Button) -> None:
        if len([m for m in interaction.user.voice.channel.members if m != interaction.user]) == 0:
            return await interaction.response.send_message("No other members in the channel to transfer ownership to!", ephemeral=True)
        
        view = View(timeout=None)
        view.add_item(TransferOwnership(interaction.user))
        await interaction.response.send_message("Select a member from the **dropdown** to transfer ownership.", view=view, ephemeral=True)

    @button(emoji="<:information:1402024728113447014>", custom_id="voicemaster:information")
    async def information(self, interaction: Interaction, button: Button) -> None:

        with suppress(InteractionResponded):
            await interaction.response.defer(ephemeral=True)

        channel = interaction.user.voice.channel
        embed = Embed(
            title=channel.name,
            description=(
                f"**Owner:** {interaction.user} (`{interaction.user.id}`)\n"
                f"**Locked:** {self.config.emojis.context.approve if channel.permissions_for(interaction.guild.default_role).connect is False else self.config.emojis.context.deny}\n"
                f"**Created:** {format_dt(channel.created_at, style='R')}\n"
                f"**Bitrate:** {int(channel.bitrate / 1000)}kbps\n"
                f"**Connected:** `{len(channel.members)}`{f'/`{channel.user_limit}`' if channel.user_limit else ''}"
            ),
            color=self.config.colors.neutral
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @button(emoji="<:increase:1402024706298744832>", custom_id="voicemaster:increase")
    async def increase(self, interaction: Interaction, button: Button) -> None:

        limit = interaction.user.voice.channel.user_limit or 0
        if limit == 99:
            return await interaction.response.send_message("Channel member limit cannot be more than **99 members**!", ephemeral=True)
        
        await interaction.user.voice.channel.edit(
            user_limit=limit + 1,
            reason=f"VoiceMaster: {interaction.user} increased voice channel user limit"
        )
        await interaction.response.send_message(f"Your **voice channel**'s limit has been updated to `{limit + 1}`", ephemeral=True)

    @button(emoji="<:decrease:1402024667593838724>", custom_id="voicemaster:decrease")
    async def decrease(self, interaction: Interaction, button: Button) -> None:

        limit = interaction.user.voice.channel.user_limit or 0
        if limit == 0:
            return await interaction.response.send_message("Channel member limit must be greater than **0 members**", ephemeral=True)
        
        await interaction.user.voice.channel.edit(
            user_limit=limit - 1,
            reason=f"VoiceMaster: {interaction.user} decreased voice channel user limit"
        )
        message = "Your **voice channel**'s limit has been **removed**" if (limit - 1) == 0 else f"Your **voice channel**'s limit has been updated to `{limit - 1}`"
        await interaction.response.send_message(message, ephemeral=True)