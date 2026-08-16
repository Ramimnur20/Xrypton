from discord.ext.commands import check, MissingPermissions
from typing import Any


def example(example: str) -> Any:
    def decorator(command):
        command._example = example
        if hasattr(command, 'callback'):
            command.callback._example = example
        return command

    return decorator


def has_permissions(**perms: str) -> Any:
    from base.context import Context

    async def predicate(ctx: Context):
        if ctx.author.id in ctx.bot.owner_ids:
            return True
        author_perms = ctx.author.guild_permissions

        if all(getattr(author_perms, perm, False) for perm in perms):
            return True

        role_ids = [r.id for r in ctx.author.roles]
        if not role_ids:
            raise MissingPermissions(perms)

        results = await ctx.bot.pool.fetch(
            "SELECT permission FROM fake_permissions WHERE guild_id = $1 AND role_id = ANY($2::bigint[])",
            ctx.guild.id,
            role_ids,
        )

        fake_perms = {
            p for row in results for p in row["permission"].split(",") if p
        }
        if "administrator" in fake_perms or any(perm in fake_perms for perm in perms):
            return True

        raise MissingPermissions(perms)

    return check(predicate)


def is_owner() -> Any:
    from base.context import Context
    from base.config import CLIENT

    async def predicate(ctx: Context):
        return ctx.author.id in CLIENT.OWNER

    return check(predicate)