from typing import Any, Dict, Optional
from discord import Client, HTTPException, Member, VoiceState
from discord.ext.commands import BucketType, Cog, CooldownMapping

mappings: Dict[str, CooldownMapping] = {}

def handle_bucket(key: Any) -> Any:
    return key

def ratelimiter(bucket: str, key: Any, rate: int, per: float) -> Optional[int]:
    if not (mapping := mappings.get(bucket)):
        mapping = mappings[bucket] = CooldownMapping.from_cooldown(rate, per, handle_bucket)
    bucket = mapping.get_bucket(key)
    return bucket.update_rate_limit()

class VoicemasterEvents(Cog):
    def __init__(self, bot: Client):
        self.bot = bot

    @Cog.listener("on_voice_state_update")
    async def create_channel(self, member: Member, before: VoiceState, after: VoiceState) -> None:
        if not after.channel:
            return
        elif before and before.channel == after.channel:
            return
        elif not (configuration := await self.bot.pool.fetchrow(
            "SELECT * FROM configuration WHERE guild_id = $1",
            member.guild.id
        )):
            return
        elif configuration.get("channel_id") != after.channel.id:
            return

        if retry_after := ratelimiter("voicemaster:create", key=member, rate=1, per=10):
            try:
                await member.move_to(None)
            except HTTPException:
                pass
            return

        channel = await member.guild.create_voice_channel(
            name=f"{member.display_name}'s channel",
            category=(
                member.guild.get_channel(configuration.get("category_id"))
                or after.channel.category
            ),
            bitrate=(
                (bitrate := configuration.get("bitrate", int(member.guild.bitrate_limit)))
                and (
                    bitrate
                    if bitrate <= int(member.guild.bitrate_limit)
                    else int(member.guild.bitrate_limit)
                )
            ),
            rtc_region=configuration.get("region"),
            reason=f"VoiceMaster: Created a voice channel for {member}"
        )

        try:
            await member.move_to(channel, reason="VoiceMaster: Created their own voice channel")
        except HTTPException:
            await channel.delete(reason="VoiceMaster: Failed to move member")
            return

        await channel.set_permissions(
            member,
            read_messages=True,
            connect=True,
            reason=f"VoiceMaster: {member} created a new voice channel"
        )

        await self.bot.pool.execute(
            "INSERT INTO channels (guild_id, channel_id, owner_id) VALUES ($1, $2, $3)",
            member.guild.id, channel.id, member.id
        )

        if (role := member.guild.get_role(configuration.get("role_id"))) and role not in member.roles:
            try:
                await member.add_roles(role, reason="VoiceMaster: Gave the owner the default role")
            except Exception:
                pass

    @Cog.listener("on_voice_state_update")
    async def remove_channel(self, member: Member, before: VoiceState, after: VoiceState) -> None:
        if not before.channel:
            return
        elif after and before.channel == after.channel:
            return

        if (
            (role_id := await self.bot.pool.fetchval(
                "SELECT role_id FROM configuration WHERE guild_id = $1",
                member.guild.id
            ))
            and role_id in (role.id for role in member.roles)
        ):
            try:
                await member.remove_roles(
                    member.guild.get_role(role_id),
                    reason="VoiceMaster: Removed the default role"
                )
            except Exception:
                pass

        if list(filter(lambda m: not m.bot, before.channel.members)):
            return
        elif not (owner_id := await self.bot.pool.fetchval(
            "DELETE FROM channels WHERE channel_id = $1 RETURNING owner_id",
            before.channel.id
        )):
            return

        try:
            await before.channel.delete()
        except HTTPException:
            pass

async def setup(bot):
    await bot.add_cog(VoicemasterEvents(bot))