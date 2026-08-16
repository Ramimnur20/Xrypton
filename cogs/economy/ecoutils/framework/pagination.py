import discord
from discord.ui import View, Button

# Local copies of the navigation emojis so this shim does not depend on the
# full `base` package (which pulls in heavy optional deps like playwright).
EMOJIS = type(
    "Emojis",
    (),
    {
        "PREVIOUS": "\u25c0",  # ◀
        "NEXT": "\u25b6",  # ▶
        "CANCEL": "\u274c",  # ❌
    },
)()


class Paginator(View):
    """Pagination view compatible with the API the economy cog expects.

    Supports: nav buttons, owner-only interaction checks, persistent items,
    dynamic per-page items via an ``on_page_switch`` callback, and reassigning
    ``.pages`` at runtime.
    """

    def __init__(
        self,
        ctx,
        pages: list,
        hide_nav: bool = False,
        hide_footer: bool = True,
        arrows_only: bool = True,
        only_for_owner: bool = True,
        on_page_switch=None,
    ):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.index = 0
        self.message = None
        self._persistent = []
        self._on_page_switch = on_page_switch
        self._only_owner = only_for_owner
        self._arrows_only = arrows_only
        if not hide_nav:
            self._add_nav()

    def _add_nav(self):
        prev = Button(
            style=discord.ButtonStyle.grey,
            emoji=EMOJIS.PREVIOUS,
            custom_id="utils_paginator_prev",
        )
        nxt = Button(
            style=discord.ButtonStyle.grey,
            emoji=EMOJIS.NEXT,
            custom_id="utils_paginator_next",
        )
        cancel = Button(
            style=discord.ButtonStyle.danger,
            emoji=EMOJIS.CANCEL,
            custom_id="utils_paginator_cancel",
        )
        prev.callback = self._prev
        nxt.callback = self._next
        cancel.callback = self._cancel
        self.add_item(prev)
        self.add_item(nxt)
        if not self._arrows_only:
            self.add_item(cancel)
        else:
            # keep cancel available but as a third button when not arrows-only only
            self.add_item(cancel)

    async def _prev(self, interaction: discord.Interaction):
        if self.index > 0:
            self.index -= 1
        else:
            self.index = len(self.pages) - 1
        await self._switch(interaction)

    async def _next(self, interaction: discord.Interaction):
        if self.index < len(self.pages) - 1:
            self.index += 1
        else:
            self.index = 0
        await self._switch(interaction)

    async def _cancel(self, interaction: discord.Interaction):
        self.stop()
        try:
            await interaction.response.defer()
        except Exception:
            pass
        try:
            await interaction.delete_original_response()
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass

    async def _switch(self, interaction: discord.Interaction):
        if self._on_page_switch:
            try:
                await self._on_page_switch(self)
            except Exception:
                pass
            # The page switch callback above already updated the message,
            # so just acknowledge the interaction.
            try:
                await interaction.response.defer()
            except Exception:
                pass
            return
        try:
            await interaction.response.edit_message(
                embed=self.pages[self.index], view=self
            )
        except Exception:
            try:
                await interaction.edit_original_response(
                    embed=self.pages[self.index], view=self
                )
            except Exception:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._only_owner and interaction.user.id != self.ctx.author.id:
            await interaction.warn("You're not the author of this embed!")
            return False
        return True

    def add_persistent_item(self, item):
        self._persistent.append(item)
        self.add_item(item)

    def remove_item(self, item):
        if item in self._persistent:
            self._persistent.remove(item)
        super().remove_item(item)

    async def start(self, file=None):
        self.message = await self.ctx.send(
            embed=self.pages[self.index], view=self, file=file
        )
        return self.message
