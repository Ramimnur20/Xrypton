import typing
import inspect

from typing import List
from dataclasses import dataclass
from discord.ext.commands import Command


@dataclass
class Parameter:
    name: str
    optional: bool


@property
def example(self: Command) -> str:
    return self.__original_kwargs__.get("example", "")


@property
def parameters(self: Command) -> str:
    return ", ".join(
        name
        for name, param in list(inspect.signature(self.callback).parameters.items())[2:]
    )


@property
def permissions(self: Command) -> List[str]:
    return [
        perm.replace("_", " ")
        for check in self.checks
        if hasattr(check, "__closure__")
        for cell in check.__closure__
        for perm, val in (
            cell.cell_contents.items() if isinstance(cell.cell_contents, dict) else []
        )
        if val
    ] or [""]


Command.example = example
Command.parameters = parameters
Command.permissions = permissions
