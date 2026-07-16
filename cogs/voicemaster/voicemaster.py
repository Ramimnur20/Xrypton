from typing import Any, Dict, List, Optional, Union
from discord import CategoryChannel, Embed, HTTPException, Member, Message, RateLimited, Role
from discord.ext import tasks
from discord.ext.commands import BucketType, Cog, CommandError, CooldownMapping, cooldown, group, has_permissions
from discord.utils import format_dt
from base.context import Context
from .events import VoicemasterEvents
from .views import Interface

mappings: Dict[str, CooldownMapping] = {}

class Voicemaster(Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(Interface(self.bot))
        
        schedule_deletion: List[int] = list()

        for row in await self.bot.pool.fetch("SELECT channel_id FROM channels"):
            channel_id: int = row.get("channel_id")
            if channel := self.bot.get_channel(channel_id):
                if not channel.members:
                    try:
                        await channel.delete(reason="VoiceMaster: Flush empty voice channels")
                    except HTTPException:
                        pass
                    schedule_deletion.append(channel_id)
            else:
                schedule_deletion.append(channel_id)

        if schedule_deletion:
            await self.bot.pool.executemany(
                "DELETE FROM channels WHERE channel_id = $1",
                [(channel_id,) for channel_id in schedule_deletion]
            )
        self.voicemaster_clear_loop.start()

    @tasks.loop(minutes=1)
    async def voicemaster_clear_loop(self):
        schedule_deletion: List[int] = list()

        for row in await self.bot.pool.fetch("SELECT channel_id FROM channels"):
            channel_id: int = row.get("channel_id")
            if channel := self.bot.get_channel(channel_id):
                if not channel.members:
                    try:
                        await channel.delete(reason="VoiceMaster: Flush empty voice channels")
                    except HTTPException:
                        pass
                    schedule_deletion.append(channel_id)
            else:
                schedule_deletion.append(channel_id)

        if schedule_deletion:
            await self.bot.pool.executemany(
                "DELETE FROM channels WHERE channel_id = $1",
                [(channel_id,) for channel_id in schedule_deletion]
            )

    async def cog_check(self, ctx: Context) -> bool:
        if ctx.command.qualified_name in (
            "voicemaster",
            "voicemaster setup",
            "voicemaster reset",
            "voicemaster category",
            "voicemaster defaultrole",
            "voicemaster defaultregion",
            "voicemaster defaultbitrate",
        ):
            return True

        if not ctx.author.voice:
            raise CommandError("You're not connected to a **voice channel**")

        elif not (owner_id := await ctx.bot.pool.fetchval(
            "SELECT owner_id FROM channels WHERE channel_id = $1",
            ctx.author.voice.channel.id
        )):
            raise CommandError("You're not in a **VoiceMaster** channel!")

        elif ctx.command.qualified_name == "voicemaster claim":
            if ctx.author.id == owner_id:
                raise CommandError("You already have **ownership** of this voice channel!")
            elif owner_id in (member.id for member in ctx.author.voice.channel.members):
                raise CommandError("You can't claim this **voice channel**, the owner is still active here.")
            return True

        elif ctx.author.id != owner_id:
            raise CommandError("You don't own a **voice channel**!")

        return True

    @group(name="voicemaster", aliases=["voice", "vm", "vc"], invoke_without_command=True)
    async def voicemaster(self, ctx: Context) -> Message:
        """Make temporary voice channels in your server!"""
        if ctx.invoked_subcommand is None:
            return await ctx.send_help(ctx.command.qualified_name)

    @voicemaster.command(name="setup")
    @has_permissions(manage_guild=True)
    @cooldown(1, 30, BucketType.guild)
    async def voicemaster_setup(self, ctx: Context) -> Message:
        """Begin VoiceMaster server configuration setup"""
        if await self.bot.pool.fetchrow(
            "SELECT * FROM configuration WHERE guild_id = $1",
            ctx.guild.id
        ):
            return await ctx.warn("Server is already configured for **VoiceMaster**, run `voicemaster reset` to reset the **VoiceMaster** server configuration")

        category = await ctx.guild.create_category("Voice Channels")
        interface = await category.create_text_channel("interface")
        channel = await category.create_voice_channel("Join to Create")

        everyone_role = ctx.guild.default_role
        await interface.set_permissions(
            everyone_role,
            send_messages=False,
            send_messages_in_threads=False,
            create_public_threads=False,
            create_private_threads=False
        )

        await channel.set_permissions(
            everyone_role,
            send_messages=False,
            send_messages_in_threads=False,
            create_public_threads=False,
            create_private_threads=False
        )

        embed = Embed(
            title="VoiceMaster Interface",
            description="Click the buttons below to control your voice channel",
            color=ctx.config.colors.information
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        embed.set_thumbnail(url=self.bot.user.display_avatar)

        embed.add_field(
            name="**Button Usage**",
            value=(
                f"{ctx.config.emojis.interface.lock} — [`Lock`](https://xrypton.vercel.app/) the voice channel\n"
                f"{ctx.config.emojis.interface.unlock} — [`Unlock`](https://xrypton.vercel.app/) the voice channel\n"
                f"{ctx.config.emojis.interface.ghost} — [`Ghost`](https://xrypton.vercel.app/) the voice channel\n"
                f"{ctx.config.emojis.interface.reveal} — [`Reveal`](https://xrypton.vercel.app/) the voice channel\n"
                f"{ctx.config.emojis.interface.claim} — [`Claim`](https://xrypton.vercel.app/) the voice channel\n"
                f"{ctx.config.emojis.interface.disconnect} — [`Disconnect`](https://xrypton.vercel.app/) a member\n"
                f"{ctx.config.emojis.interface.activity} — [`Start`](https://xrypton.vercel.app/) an activity\n"
                f"{ctx.config.emojis.interface.information} — [`View`](https://xrypton.vercel.app/) channel information\n"
                f"{ctx.config.emojis.interface.increase} — [`Increase`](https://xrypton.vercel.app/) the user limit\n"
                f"{ctx.config.emojis.interface.decrease} — [`Decrease`](https://xrypton.vercel.app/) the user limit\n"
                f"{ctx.config.emojis.interface.transfer} — [`Transfer`](https://xrypton.vercel.app/) the voice channel to another person\n"
            )
        )

        await interface.send(embed=embed, view=Interface(self.bot))

        await self.bot.pool.execute(
            "INSERT INTO configuration (guild_id, category_id, interface_id, channel_id) VALUES ($1, $2, $3, $4)",
            ctx.guild.id, category.id, interface.id, channel.id
        )

        return await ctx.approve("Finished setting up the **VoiceMaster** channels. A category and two channels have been created, you can move the channels or rename them if you want.")

    @voicemaster.command(name="reset", aliases=["resetserver"])
    @has_permissions(manage_guild=True)
    @cooldown(1, 60, BucketType.guild)
    async def voicemaster_reset(self, ctx: Context) -> Message:
        """Reset server configuration for VoiceMaster"""
        if channel_ids := await self.bot.pool.fetchrow(
            "DELETE FROM configuration WHERE guild_id = $1 RETURNING category_id, interface_id, channel_id",
            ctx.guild.id
        ):
            for channel in (
                channel
                for channel_id in channel_ids
                if (channel := ctx.guild.get_channel(channel_id))
            ):
                await channel.delete()
            return await ctx.approve("Reset the **VoiceMaster** configuration")
        else:
            return await ctx.warn("Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command")

    @voicemaster.command(name="category")
    @has_permissions(manage_guild=True)
    async def voicemaster_category(self, ctx: Context, *, channel: CategoryChannel) -> Message:
        """Redirect voice channels to custom category"""
        try:
            await self.bot.pool.execute(
                "UPDATE configuration SET category_id = $2 WHERE guild_id = $1",
                ctx.guild.id, channel.id
            )
        except Exception:
            return await ctx.warn("Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command")
        return await ctx.approve(f"Set **{channel}** as the default voice channel category")

    @voicemaster.command(name="defaultrole")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def voicemaster_defaultrole(self, ctx: Context, *, role: Role) -> Message:
        """Set a role that members get for being in a VM channel"""
        try:
            await self.bot.pool.execute(
                "UPDATE configuration SET role_id = $2 WHERE guild_id = $1",
                ctx.guild.id, role.id
            )
        except Exception:
            return await ctx.warn("Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command")
        return await ctx.approve(f"Set {role.mention} as the default role for members in voice channels")

    @voicemaster.command(name="defaultregion")
    @has_permissions(manage_guild=True)
    async def voicemaster_defaultregion(self, ctx: Context, *, region: str) -> Message:
        """Edit default region for new Voice Channels"""
        try:
            await self.bot.pool.execute(
                "UPDATE configuration SET region = $2 WHERE guild_id = $1",
                ctx.guild.id, region
            )
        except Exception:
            return await ctx.warn("Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command")
        return await ctx.approve(f"Set **{region}** as the default voice channel region")

    @voicemaster.command(name="defaultbitrate")
    @has_permissions(manage_guild=True)
    async def voicemaster_defaultbitrate(self, ctx: Context, *, bitrate: int) -> Message:
        """Edit default bitrate for new Voice Channels"""
        try:
            await self.bot.pool.execute(
                "UPDATE configuration SET bitrate = $2 WHERE guild_id = $1",
                ctx.guild.id, bitrate
            )
        except Exception:
            return await ctx.warn("Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command")
        return await ctx.approve(f"Set `{bitrate}` as the default voice channel bitrate")

    @voicemaster.command(name="configuration", aliases=["config", "show", "view", "info"])
    async def voicemaster_configuration(self, ctx: Context) -> Message:
        """See current configuration for current voice channel"""
        channel = ctx.author.voice.channel
        embed = Embed(
            color=ctx.config.colors.neutral,
            title=channel.name,
            description=(
                f"**Owner:** {ctx.author} (`{ctx.author.id}`)\n"
                f"**Locked:** {ctx.config.emojis.context.approve if channel.permissions_for(ctx.guild.default_role).connect is False else ctx.config.emojis.context.deny}\n"
                f"**Created:** {format_dt(channel.created_at, style='R')}\n"
                f"**Bitrate:** {int(channel.bitrate / 1000)}kbps\n"
                f"**Connected:** `{len(channel.members)}`{f'/`{channel.user_limit}`' if channel.user_limit else ''}"
            )
        )
        return await ctx.send(embed=embed)

    @voicemaster.command(name="claim")
    async def voicemaster_claim(self, ctx: Context) -> Message:
        """Claim an inactive voice channel"""
        await self.bot.pool.execute(
            "UPDATE channels SET owner_id = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, ctx.author.id
        )
        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(name=f"{ctx.author.display_name}'s channel")
            except Exception:
                pass
        return await ctx.approve("You are now the owner of this **channel**!")

    @voicemaster.command(name="transfer")
    async def voicemaster_transfer(self, ctx: Context, *, member: Member) -> Message:
        """Transfer ownership of your channel to another member"""
        if member == ctx.author or member.bot:
            return await ctx.send_help()
        elif not member.voice or member.voice.channel != ctx.author.voice.channel:
            return await ctx.warn(f"**{member}** is not in your channel!")
        
        await self.bot.pool.execute(
            "UPDATE channels SET owner_id = $2 WHERE channel_id = $1",
            ctx.author.voice.channel.id, member.id
        )
        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(name=f"{member.display_name}'s channel")
            except Exception:
                pass
        return await ctx.approve(f"**{member}** now has ownership of this channel")

    @voicemaster.command(name="name", aliases=["rename"])
    async def voicemaster_name(self, ctx: Context, *, name: str) -> Message:
        """Rename your voice channel"""
        if len(name) > 100:
            return await ctx.warn("Your channel's name cannot be longer than **100 characters**")
        
        if ctx.author.voice.channel.id not in mappings:
            mappings[ctx.author.voice.channel.id] = CooldownMapping.from_cooldown(2, 60, BucketType.channel)
        
        bucket = mappings[ctx.author.voice.channel.id].get_bucket(ctx.message)
        if retry_after := bucket.update_rate_limit():
            return await ctx.warn(f"You're changing names too fast! Try again in **{retry_after:.1f} seconds**")
        
        try:
            await ctx.author.voice.channel.edit(
                name=name, 
                reason=f"VoiceMaster: {ctx.author} renamed voice channel"
            )
        except HTTPException as e:
            if e.status == 400:
                return await ctx.warn("Voice channel name cannot contain **vulgar words** or **invalid characters**")
            elif e.status == 429:
                retry_after = e.retry_after if hasattr(e, 'retry_after') else 30
                return await ctx.warn(f"Voice channel is being **rate limited**, try again in **{retry_after:.1f} seconds**")
            else:
                return await ctx.warn("Failed to rename voice channel due to an unexpected error")
        except RateLimited as e:
            retry_after = e.retry_after if hasattr(e, 'retry_after') else 30
            return await ctx.warn(f"Voice channel is being **rate limited**, try again in **{retry_after:.1f} seconds**")
        else:
            return await ctx.approve(f"Your **voice channel** has been renamed to `{name}`")

    @voicemaster.command(name="bitrate", aliases=["quality"])
    async def voicemaster_bitrate(self, ctx: Context, bitrate: int) -> Message:
        """Edit bitrate of your voice channel"""
        await ctx.author.voice.channel.edit(
            bitrate=bitrate,
            reason=f"VoiceMaster: {ctx.author} edited voice channel bitrate"
        )
        return await ctx.approve(f"Your **voice channel**'s bitrate has been updated to `{bitrate}`")

    @voicemaster.command(name="limit", aliases=["userlimit"])
    async def voicemaster_limit(self, ctx: Context, limit: int) -> Message:
        """Edit user limit of your voice channel"""
        if limit < 0:
            return await ctx.warn("Channel member limit must be greater than **0 members**")
        elif limit > 99:
            return await ctx.warn("Channel member limit cannot be more than **99 members**")
        
        await ctx.author.voice.channel.edit(
            user_limit=limit,
            reason=f"VoiceMaster: {ctx.author} edited voice channel user limit"
        )
        return await ctx.approve(f"Your **voice channel**'s limit has been updated to `{limit}`")

    @voicemaster.command(name="lock")
    async def voicemaster_lock(self, ctx: Context) -> Message:
        """Lock your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            connect=False,
            reason=f"VoiceMaster: {ctx.author} locked voice channel"
        )
        return await ctx.approve("Your **voice channel** has been locked")

    @voicemaster.command(name="unlock")
    async def voicemaster_unlock(self, ctx: Context) -> Message:
        """Unlock your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            connect=None,
            reason=f"VoiceMaster: {ctx.author} unlocked voice channel"
        )
        return await ctx.approve("Your **voice channel** has been unlocked")

    @voicemaster.command(name="ghost", aliases=["hide"])
    async def voicemaster_ghost(self, ctx: Context) -> Message:
        """Hide your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {ctx.author} made voice channel hidden"
        )
        return await ctx.approve("Your **voice channel** has been hidden")

    @voicemaster.command(name="unghost", aliases=["reveal", "unhide"])
    async def voicemaster_unghost(self, ctx: Context) -> Message:
        """Reveal your voice channel"""
        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {ctx.author} revealed voice channel"
        )
        return await ctx.approve("Your **voice channel** has been revealed")

    @voicemaster.command(name="permit", aliases=["allow"])
    async def voicemaster_permit(self, ctx: Context, *, target: Union[Member, Role]) -> Message:
        """Permit a member or role to join your VC"""
        await ctx.author.voice.channel.set_permissions(
            target,
            connect=True,
            view_channel=True,
            reason=f"VoiceMaster: {ctx.author} permitted {target} to join voice channel"
        )
        return await ctx.approve(f"Granted **connect permission** to {target.mention} to join")

    @voicemaster.command(name="reject", aliases=["remove", "deny", "kick"])
    async def voicemaster_reject(self, ctx: Context, *, target: Union[Member, Role]) -> Message:
        """Reject a member or role from joining your VC"""
        await ctx.author.voice.channel.set_permissions(
            target,
            connect=False,
            view_channel=None,
            reason=f"VoiceMaster: {ctx.author} rejected {target} from joining voice channel"
        )
        if isinstance(target, Member):
            if (voice := target.voice) and voice.channel == ctx.author.voice.channel:
                await target.move_to(None)
        return await ctx.approve(f"Removed **connect permission** from {target.mention} to join")