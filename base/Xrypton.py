import glob
import discord_ios
import os
import time
import pathlib
import re
import aiosqlite

from typing import List, Dict, Optional, Any
from datetime import datetime

from discord import (
    AllowedMentions,
    Message,
    CustomActivity,
    Intents,
    Embed,
    Guild,
    Forbidden,
    Member,
)
from discord.utils import format_dt
from discord.ext.commands import (
    AutoShardedBot,
    when_mentioned_or,
    ExtensionFailed,
    CommandError,
    CheckFailure,
    CommandNotFound,
    NotOwner,
    CommandOnCooldown,
    ChannelNotFound,
    RoleNotFound,
    ThreadNotFound,
    UserNotFound,
    MissingPermissions,
    MinimalHelpCommand,
    CooldownMapping,
    BucketType,
    MissingRequiredArgument,
    UserInputError,
    BadArgument,
)

from loguru import logger
from base.context import Context, XryptonHelp
from base.managers.browser import BrowserHandler
from collections import defaultdict
from os import environ

environ["JISHAKU_HIDE"] = "True"
environ["JISHAKU_RETAIN"] = "True"
environ["JISHAKU_NO_UNDERSCORE"] = "True"
environ["JISHAKU_SHELL_NO_DM_TRACEBACK"] = "True"


class SqlitePool:
    """Wrapper around aiosqlite to provide asyncpg-like interface."""
    
    def __init__(self, db: Any):
        self.db = db
    
    @staticmethod
    def _convert_query(query: str, params: tuple) -> tuple[str, list]:
        """Convert PostgreSQL parameterized query ($1, $2) to SQLite (?).
        
        Handles:
        - $1, $2, etc. -> ?
        - ANY($n::type[]) with list parameters -> IN (?, ?, ...)
        """
        params_list = list(params)
        
        # Handle ANY(...) with array parameters
        def replace_any(match):
            param_ref = match.group(1)  # e.g., "$2"
            param_idx = int(param_ref[1:]) - 1
            
            if param_idx < len(params_list) and isinstance(params_list[param_idx], (list, tuple)):
                # Replace the array parameter with placeholders
                placeholders = ",".join("?" * len(params_list[param_idx]))
                return f"IN ({placeholders})"
            return "?"
        
        # Replace ANY($n::type[]) patterns
        converted = re.sub(r'ANY\((\$\d+)(?::\w+\[\])?\)', replace_any, query)
        
        # Flatten list parameters for IN clauses
        expanded_params = []
        param_counter = 0
        for param in params_list:
            if isinstance(param, (list, tuple)) and param_counter < len(params_list):
                expanded_params.extend(param)
            else:
                expanded_params.append(param)
            param_counter += 1
        
        # Replace $1, $2, etc. with ?
        converted = re.sub(r'\$\d+', '?', converted)
        
        # Remove type casting like ::bigint[]
        converted = re.sub(r'::\w+(?:\[\])?', '', converted)
        
        return converted, expanded_params
    
    async def execute(self, query: str, *params) -> None:
        """Execute a query without returning results."""
        query, params = self._convert_query(query, params)
        await self.db.execute(query, params)
        await self.db.commit()
    
    async def fetchval(self, query: str, *params) -> Optional[Any]:
        """Fetch a single value (first column of first row)."""
        query, params = self._convert_query(query, params)
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        if row:
            return row[0]
        return None
    
    async def fetchrow(self, query: str, *params) -> Optional[dict]:
        """Fetch a single row as a dict."""
        query, params = self._convert_query(query, params)
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        if row:
            return dict(row) if hasattr(row, 'keys') else row
        return None
    
    async def fetch(self, query: str, *params) -> List[dict]:
        """Fetch all rows as dicts."""
        query, params = self._convert_query(query, params)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) if hasattr(row, 'keys') else row for row in rows] if rows else []


class Bot(AutoShardedBot):
    pool: SqlitePool
    boot: datetime

    def __init__(self) -> None:
        super().__init__(
            command_prefix=",",  # type: ignore
            case_insensitive=True,
            intents=Intents.all(),
            help_command=XryptonHelp(),
            allowed_mentions=AllowedMentions(
                everyone=False, roles=False, replied_user=False
            ),
            activity=CustomActivity(name="🔗 Xrypton.best/discord"),
            owner_ids=[
                1470775670262202590,
                1467913714484121725 # remove if u want
            ],
        )
        self.browser_handler = BrowserHandler()
        self._uptime = time.time()
        self.message_cache = defaultdict(list)
        self.cache_expiry_seconds = 30
        self.member_cooldown = CooldownMapping.from_cooldown(3, 5, BucketType.user)
        self.channel_cooldown = CooldownMapping.from_cooldown(4, 5, BucketType.channel)

    @property
    def ping(self) -> int:
        return round(self.latency * 1000)

    @property
    def booted(self):
        return format_dt(self.boot, style="R")

    @property
    def uptime(self) -> str:
        return self.humanize_time(self._uptime)

    @property
    def linecount(self) -> int:
        return sum(
            [
                len(f.open("r").readlines())
                for f in [
                    f
                    for f in pathlib.Path("/root/Xrypton").glob("**/*.py")
                    if f.is_file()
                ]
            ]
        )

    async def get_prefix(self, message: Message) -> tuple:
        if message.guild is None:
            return  # type: ignore

        guild_prefix = (
            await self.pool.fetchval(
                "SELECT prefix FROM prefix WHERE guild_id = $1", message.guild.id
            )
            or ","
        )

        return (guild_prefix, guild_prefix)

    async def load_modules(self, directory: str = "cogs"):
        """
        Recursively load all modules in the directory selected.

        Args:
            directory (str): This is the directory meant to contain all modules, defaults to 'extensions'.
        """
        for module in glob.glob(f"{directory}/**/*.py", recursive=True):
            module_path = (
                module.replace("/", ".")
                .replace("\\", ".")
                .replace(".__init__", "")[:-3]
            )
            try:
                await self.load_extension(module_path)
                logger.info(f"Loaded extension: {module_path}")
            except ExtensionFailed as e:
                if "has no 'setup' function" in str(e):
                    logger.info(f"Loaded extension: {module_path}")
                else:
                    logger.warning(f"Extension failed to load: {module} - {e}")
            except Exception as e:
                if "has no 'setup' function" in str(e):
                    logger.info(f"Loaded extension: {module_path}")
                else:
                    logger.warning(f"Extension error: {module} - {e}")

    async def _load_database(self) -> SqlitePool:
        try:
            # Use relative path for cross-platform compatibility
            db_path = pathlib.Path("Xrypton.db")
            schema_path = pathlib.Path("base/schema/schema.sql")
            
            db = await aiosqlite.connect(str(db_path))
            db.row_factory = aiosqlite.Row
            logger.info(f"Database connection established at {db_path}")

            if schema_path.exists():
                with open(schema_path, "r") as file:
                    schema = file.read()
                    if schema.strip():
                        # Split and execute individual statements
                        statements = [s.strip() for s in schema.split(';') if s.strip()]
                        for statement in statements:
                            await db.execute(statement)
                        await db.commit()
                        logger.info("Database schema loaded")
                    else:
                        logger.warning("Database schema file is empty")
                    file.close()
            else:
                logger.warning(f"Schema file not found at {schema_path}")

            return SqlitePool(db)  # type: ignore
        except Exception as e:
            logger.error(f"Error loading database: {e}")
            raise e

    async def setup_hook(self):
        self.pool = await self._load_database()  # type: ignore
        await self.load_modules()
        self.boot = datetime.now()
        await self.load_extension("jishaku")
        await self.browser_handler.init()
        self.browser = self.browser_handler
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} application commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        return await super().setup_hook()

    def format_size(self, bytes):
        """
        Convert bytes to a human-readable format.
        """
        if bytes >= 1024**3:
            return f"{bytes / (1024**3):.2f}GB"
        elif bytes >= 1024**2:
            return f"{bytes / (1024**2):.2f}MB"
        elif bytes >= 1024:
            return f"{bytes / 1024:.2f}KB"
        else:
            return f"{bytes} Bytes"

    def humanize_number(self, number: int) -> str:
        suffixes = ["", "k", "m", "b", "t"]
        magnitude = min(len(suffixes) - 1, (len(str(abs(number))) - 1) // 3)
        formatted_number = (
            "{:.1f}".format(number / 10 ** (3 * magnitude)).rstrip("0").rstrip(".")
        )
        return "{}{}".format(formatted_number, suffixes[magnitude])

    async def get_context(self, message: Message, *, cls=Context):  # type: ignore
        return await super().get_context(message, cls=cls)

    def humanize_time(self, start_time: float) -> str:
        uptime_seconds = abs(time.time() - start_time)
        intervals = (
            ("year", 31556952),
            ("month", 2629746),
            ("day", 86400),
            ("hour", 3600),
            ("minute", 60),
            ("second", 1),
        )

        result = []
        for name, count in intervals:
            value = uptime_seconds // count
            if value:
                uptime_seconds -= value * count
                result.append(f"{int(value)} {name}{'s' if value > 1 else ''}")

        return ", ".join(result)

    async def on_command_error(self, ctx: Context, exception: CommandError) -> None:
        exception = getattr(exception, "original", exception)  # type: ignore
        if type(exception) in (NotOwner, CheckFailure):
            return

        elif isinstance(exception, CommandOnCooldown):
            return await ctx.cooldown(
                f"Please wait **{exception.retry_after:.2f} seconds** before using this command again."
            )  # type: ignore

        elif isinstance(exception, CheckFailure):
            if isinstance(exception, MissingPermissions):
                return await ctx.warn(
                    f"You're **missing** permission: `{', '.join(p for p in exception.missing_permissions)}`"  # type: ignore
                )

        elif isinstance(exception, CommandNotFound):
            alias = ctx.message.content[len(ctx.clean_prefix) :].split(" ")[0]
            check = await self.pool.fetchval(
                "SELECT command FROM aliases WHERE guild_id = $1 AND alias = $2",
                ctx.guild.id,
                alias,
            )
            if check:
                ctx.message.content = ctx.message.content.replace(alias, check, 1)
                return await self.process_commands(ctx.message)

        elif isinstance(exception, MissingRequiredArgument):
            return await ctx.send_help(ctx.command)

        elif isinstance(exception, BadArgument):
            return await ctx.warn(exception.args[0])

        elif isinstance(exception, UserInputError):
            return await ctx.send_help(ctx.command)

        return await ctx.warn(f"{exception}")

    async def on_message_edit(self, before, after):
        if before.content == after.content:
            return
        if after.author.bot:
            return

        ctx = await self.get_context(after)
        if ctx.valid:
            await self.invoke(ctx)

    async def log_lost_boost(self, member: Member):
        try:
            query = """
            INSERT OR REPLACE INTO lost_boosters (guild_id, user_id, username, discriminator, lost_at)
            VALUES (?, ?, ?, ?, ?)
            """
            await self.pool.execute(
                query,
                member.guild.id,
                member.id,
                member.name,
                member.discriminator,
                datetime.utcnow(),
            )  # type: ignore
            print(f"Logged lost boost for {member.name}#{member.discriminator}")
        except Exception as e:
            print(f"Error logging lost boost: {e}")

    async def on_message(self, message: Message) -> None:
        if message.author.bot:
            return

        check = await self.pool.fetchrow(
            "SELECT * FROM blacklist WHERE user_id = $1", message.author.id
        )
        if check:
            return

        prefix = await self.get_prefix(message)
        if not message.content.startswith(tuple(prefix)):
            return

        now = time.time()
        author_id = message.author.id

        self.message_cache[author_id] = [
            timestamp
            for timestamp in self.message_cache[author_id]
            if now - timestamp < self.cache_expiry_seconds
        ]
        self.message_cache[author_id].append(now)

        await self.process_commands(message)

    async def on_command(self, ctx) -> None:
        logger.info(
            f"{ctx.author} ({ctx.author.id}) executed {ctx.command} in {ctx.guild} ({ctx.guild.id})."
        )

    async def on_shard_ready(self, ctx) -> None:
        logger.debug(f"Shard {self.shard_id} has spawned.")

    def member_ratelimit(self, message: Message) -> Optional[int]:
        bucket = self.member_cooldown.get_bucket(message)
        return bucket.update_rate_limit()  # type: ignore

    def channel_ratelimit(self, message: Message) -> Optional[int]:
        bucket = self.channel_cooldown.get_bucket(message)
        return bucket.update_rate_limit()  # type: ignore

    async def process_commands(
        self: "Bot",
        message: Message,
    ):
        if message.content.startswith(tuple(await self.get_prefix(message))):
            mcd = self.member_ratelimit(message)
            ccd = self.channel_ratelimit(message)

            if mcd or ccd:
                return

            return await super().process_commands(message)
