from typing import Union
from collections import defaultdict
import requests
import io
import time
import aiohttp
import shazamio
from shazamio import Shazam, Serialize
from re import match

from base.managers.types import CogMeta
from base.context import Context
from base.managers.paginator import *
from base.config import *
from random import random, choice, randint
from humanize import naturaltime
import humanize
from datetime import datetime
import time
from base.managers.EmbedBuilder import *
from discord.ui import Button, View
from discord import ButtonStyle
from discord.ui import View, Button, Modal, TextInput


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
    hybrid_command,
    group,
    Cog,
    has_permissions,
)
from discord.ui import View
import discord
from discord.utils import format_dt, oauth_url
from datetime import datetime, timedelta
from nudenet import NudeDetector
import asyncio
from psutil import Process
from difflib import get_close_matches


class Fun(CogMeta):
    @command(
        name="howgay", aliases=["gayrate", "gay"], description="See how gay a user is."
    )
    async def howgay(self, ctx: Context, *, user: Union[Member, User] = Author):
        return await ctx.embed(
            description=f"{user.mention} is **{randint(1, 100)}%** gay 🏳️‍🌈"
        )
