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
