from typing import Optional


class CommandCache:
    """Minimal stand-in for utils's CommandCache.

    Provides a way to resolve a human-readable / mentionable reference to a
    command by its qualified name.
    """

    @staticmethod
    async def get_mention(bot, name: str) -> str:
        command = bot.get_command(name)
        if command is not None:
            try:
                mention = command.mention
                if mention:
                    return mention
            except Exception:
                pass
        return f"`/{name}`"
