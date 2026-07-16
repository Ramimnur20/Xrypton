import discord
import asyncio
import aiohttp
import random
import secrets
from typing import Optional

from discord import app_commands, Embed, ButtonStyle, Interaction
from discord.ext.commands import Cog, hybrid_group, hybrid_command
from discord.ui import View, Button

from base.config import *


async def get_user_color(bot, user_id: int) -> int:
    """Pulls the user's custom embed color from the Customize cog if it's loaded, else falls back."""
    customize = bot.get_cog("Customize")
    if customize and hasattr(customize, "get_color"):
        try:
            return await customize.get_color(user_id)
        except Exception:
            pass
    return COLORS.neutral


# ---------- Tic Tac Toe ----------

class TicTacToeButton(Button):
    def __init__(self, game_id, x, y):
        super().__init__(style=ButtonStyle.secondary, label="\u200b", row=x, custom_id=f"tictactoe_{game_id}_{x}_{y}")
        self.game_id = game_id
        self.x = x
        self.y = y

    async def callback(self, interaction: Interaction):
        view: TicTacToeView = self.view
        if self.game_id != view.game_id:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        state = view.board[self.x][self.y]

        if state in (view.X, view.O):
            await interaction.response.send_message("This tile is already claimed.", ephemeral=True)
            return

        if interaction.user.id != view.player1.id and interaction.user.id != view.player2.id:
            await interaction.response.send_message("You aren't participating in this game.", ephemeral=True)
            return

        if interaction.user.id != view.current_turn:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if interaction.user.id == view.player1.id:
            self.style = ButtonStyle.danger
            self.label = "X"
            view.board[self.x][self.y] = view.X
            view.current_turn = view.player2.id
        else:
            self.style = ButtonStyle.success
            self.label = "O"
            view.board[self.x][self.y] = view.O
            view.current_turn = view.player1.id

        winner = view.check_winner()
        if winner:
            for child in view.children:
                child.disabled = True

            if winner == view.X:
                content = f"**{view.player1.display_name}** vs **{view.player2.display_name}**\n\n🏅 {view.player1.mention} won!"
            elif winner == view.O:
                content = f"**{view.player1.display_name}** vs **{view.player2.display_name}**\n\n🏅 {view.player2.mention} won!"
            else:
                content = f"**{view.player1.display_name}** vs **{view.player2.display_name}**\n\n🔎 Nobody won! It's a tie."

            await interaction.response.edit_message(content=content, view=view)
        else:
            turn_mention = view.player1.mention if view.current_turn == view.player1.id else view.player2.mention
            symbol = "⭕" if view.current_turn == view.player1.id else "❌"
            content = f"**{view.player1.display_name}** vs **{view.player2.display_name}**\n\n{symbol} {turn_mention}, your turn."
            await interaction.response.edit_message(content=content, view=view)


class TicTacToeView(View):
    X = -1
    O = 1
    Tie = 2

    def __init__(self, player1: discord.Member, player2: discord.Member, game_id: str):
        super().__init__(timeout=300)
        self.game_id = game_id
        self.board = [[0] * 3 for _ in range(3)]
        self.current_turn = player1.id
        self.player1 = player1
        self.player2 = player2
        self.message = None

        for x in range(3):
            for y in range(3):
                self.add_item(TicTacToeButton(game_id, x, y))

    def check_winner(self):
        for row in self.board:
            if abs(sum(row)) == 3:
                return self.X if row[0] == self.X else self.O

        for col in range(3):
            col_sum = self.board[0][col] + self.board[1][col] + self.board[2][col]
            if abs(col_sum) == 3:
                return self.X if self.board[0][col] == self.X else self.O

        diag1 = [self.board[0][0], self.board[1][1], self.board[2][2]]
        diag2 = [self.board[0][2], self.board[1][1], self.board[2][0]]
        if abs(sum(diag1)) == 3:
            return self.X if diag1[0] == self.X else self.O
        if abs(sum(diag2)) == 3:
            return self.X if diag2[0] == self.X else self.O

        if all(cell != 0 for row in self.board for cell in row):
            return self.Tie

        return None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

        try:
            await self.message.edit(
                content=f"**{self.player1.display_name}** vs **{self.player2.display_name}**\n\n⏰ The game has timed out!",
                view=self,
            )
        except Exception:
            pass


class TTTAcceptButton(Button):
    def __init__(self, author: discord.Member):
        super().__init__(style=ButtonStyle.green, emoji="✅")
        self.author = author

    async def callback(self, interaction: Interaction):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("You can't play against yourself!", ephemeral=True)
            return
        game_id = str(secrets.token_hex(8))
        view = TicTacToeView(self.author, interaction.user, game_id)
        content = f"**{self.author.display_name}** vs **{interaction.user.display_name}**\n\n⭕ {self.author.mention}, your turn."
        await interaction.response.edit_message(content=content, view=view)
        view.message = await interaction.original_response()


class TTTInviteView(View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=240)
        self.author = author
        self.message = None
        self.add_item(TTTAcceptButton(author))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(content="⏰ The game invitation has expired.", view=self)
        except Exception:
            pass


# ---------- Snake ----------

class SnakeButton(Button):
    def __init__(self, label, custom_id):
        super().__init__(style=ButtonStyle.primary, label=label, custom_id=custom_id)

    async def callback(self, interaction: Interaction):
        await Games.update_snake_game(interaction, self.custom_id)


# ---------- Rock Paper Scissors ----------

class RPSAcceptButton(Button):
    def __init__(self, author: discord.Member, bot):
        super().__init__(style=ButtonStyle.green, emoji="✅", custom_id=f"accept_rps_{author.id}")
        self.author = author
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("You can't play against yourself!", ephemeral=True)
            return

        color = await get_user_color(self.bot, self.author.id)
        embed = discord.Embed(title="Any of you can go first", description="-# Click a button to make your move", color=color)
        view = RPSGameView(self.author, interaction.user, self.bot)
        content = f"{self.author.mention} {interaction.user.mention}"
        await interaction.response.edit_message(content=content, embed=embed, view=view)
        view.message = await interaction.original_response()


class RPSButton(Button):
    def __init__(self, emoji: str, choice: str, player1: discord.Member, player2: discord.Member):
        super().__init__(style=ButtonStyle.secondary, emoji=emoji)
        self.choice = choice
        self.player1 = player1
        self.player2 = player2

    async def callback(self, interaction: discord.Interaction):
        view: RPSGameView = self.view

        await interaction.response.defer()

        if interaction.user.id not in (view.player1.id, view.player2.id):
            await interaction.followup.send("You're not part of this game!", ephemeral=True)
            return

        if interaction.user.id == view.player1.id:
            if view.player1_choice is not None:
                await interaction.followup.send("You've already made your choice!", ephemeral=True)
                return
            view.player1_choice = self.choice
        else:
            if view.player2_choice is not None:
                await interaction.followup.send("You've already made your choice!", ephemeral=True)
                return
            view.player2_choice = self.choice

        if view.player1_choice and not view.player2_choice:
            content = f"{view.player2.mention}"
            color = await get_user_color(view.bot, interaction.user.id)
            embed = discord.Embed(
                description=f"{view.player1.display_name} locked their choice\n{view.player2.display_name} is choosing...",
                color=color,
            )
            await view.message.edit(content=content, embed=embed)
        elif view.player2_choice and not view.player1_choice:
            content = f"{view.player1.mention}"
            color = await get_user_color(view.bot, interaction.user.id)
            embed = discord.Embed(
                description=f"{view.player2.display_name} locked their choice\n{view.player1.display_name} is choosing...",
                color=color,
            )
            await view.message.edit(content=content, embed=embed)
        else:
            await view.check_winner()


class RPSGameView(View):
    def __init__(self, player1: discord.Member, player2: discord.Member, bot):
        super().__init__(timeout=240)
        self.player1 = player1
        self.player2 = player2
        self.player1_choice = None
        self.player2_choice = None
        self.bot = bot
        self.message = None
        self.add_item(RPSButton("🪨", "rock", player1, player2))
        self.add_item(RPSButton("📄", "paper", player1, player2))
        self.add_item(RPSButton("✂️", "scissors", player1, player2))

    async def check_winner(self):
        if self.player1_choice and self.player2_choice:
            if self.player1_choice == self.player2_choice:
                winner = "tie"
            elif (self.player1_choice == "rock" and self.player2_choice == "scissors") or \
                 (self.player1_choice == "paper" and self.player2_choice == "rock") or \
                 (self.player1_choice == "scissors" and self.player2_choice == "paper"):
                winner = self.player1
            else:
                winner = self.player2

            for child in self.children:
                child.disabled = True

            symbols = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
            emoji1 = symbols[self.player1_choice]
            emoji2 = symbols[self.player2_choice]

            if winner == "tie":
                result = f"**It's a tie!**\n\n-# {self.player1.display_name} chose {emoji1} & {self.player2.display_name} chose {emoji2}"
            else:
                winning_emoji = emoji1 if winner == self.player1 else emoji2
                result = f"**{winner.mention} won with {winning_emoji}**\n\n-# {self.player1.display_name} chose {emoji1} & {self.player2.display_name} chose {emoji2}"

            color = await get_user_color(self.bot, self.player1.id)
            embed = discord.Embed(description=result, color=color)
            try:
                await self.message.edit(content=None, embed=embed, view=self)
            except Exception:
                pass
            self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(description="Game timed out, feel free to start another.", color=0x2B2D31)
        try:
            await self.message.edit(embed=embed, view=self)
        except Exception:
            pass


# ---------- Blackjack ----------

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♣", "♦", "♥", "♠"]


def build_deck() -> list:
    deck = [f"{rank}{suit}" for rank in RANKS for suit in SUITS]
    random.shuffle(deck)
    return deck


def card_value(card: str) -> int:
    rank = card[:-1]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def calculate_hand_value(hand: list) -> int:
    value = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1] == "A")
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def format_hand(hand: list) -> str:
    return " ".join(f"`{c}`" for c in hand)


class BlackjackButton(Button):
    def __init__(self, author: discord.Member, bot):
        super().__init__(style=ButtonStyle.green, emoji="✅", custom_id=f"accept_blackjack_{author.id}")
        self.author = author
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("You cannot play against yourself!", ephemeral=True)
            return

        deck = build_deck()
        player1_hand = [deck.pop(), deck.pop()]
        player2_hand = [deck.pop(), deck.pop()]

        color = await get_user_color(self.bot, interaction.user.id)
        embed = discord.Embed(
            description=(
                f"### __{self.author.mention}'s turn__\n"
                f"**{self.author.display_name}'s hand ({calculate_hand_value(player1_hand)})**\n"
                f"### {format_hand(player1_hand)}\n"
                f"**{interaction.user.display_name}'s hand ({calculate_hand_value(player2_hand)})**\n"
                f"### {format_hand(player2_hand)}"
            ),
            color=color,
        )
        embed.set_author(name=f"{self.author.name} vs {interaction.user.name}")
        embed.set_thumbnail(url=self.author.display_avatar.url)

        view = BlackjackView(self.author, interaction.user, deck, player1_hand, player2_hand, self.bot)
        await interaction.response.edit_message(content=None, embed=embed, view=view)
        view.message = await interaction.original_response()


class BlackjackView(View):
    def __init__(self, player1: discord.Member, player2: discord.Member, deck: list, player1_hand: list, player2_hand: list, bot):
        super().__init__(timeout=240)
        self.player1 = player1
        self.player2 = player2
        self.deck = deck
        self.player1_hand = player1_hand
        self.player2_hand = player2_hand
        self.current_turn = player1
        self.game_finished = False
        self.double_down_disabled = True
        self.bot = bot
        self.message = None
        self.update_buttons()

    def update_buttons(self):
        for item in self.children:
            if getattr(item, "label", None) == "Double Down":
                item.disabled = self.double_down_disabled
                item.style = ButtonStyle.gray if self.double_down_disabled else ButtonStyle.secondary

    async def update_embed(self):
        description = (
            f"### __{self.current_turn.mention}'s turn__\n"
            f"**{self.player1.display_name}'s hand ({calculate_hand_value(self.player1_hand)})**\n"
            f"### {format_hand(self.player1_hand)}\n"
            f"**{self.player2.display_name}'s hand ({calculate_hand_value(self.player2_hand)})**\n"
            f"### {format_hand(self.player2_hand)}"
        )
        color = await get_user_color(self.bot, self.current_turn.id)
        embed = discord.Embed(description=description, color=color)
        embed.set_author(name=f"{self.player1.name} vs {self.player2.name}")
        embed.set_thumbnail(url=self.current_turn.display_avatar.url)
        return embed

    async def check_for_21(self):
        player1_value = calculate_hand_value(self.player1_hand)
        player2_value = calculate_hand_value(self.player2_hand)

        if player1_value == 21 or player2_value == 21:
            await self.end_game(None, "21")

    @discord.ui.button(label="Hit", style=ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.current_turn.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if self.current_turn == self.player1:
            self.player1_hand.append(self.deck.pop())
            if calculate_hand_value(self.player1_hand) > 21:
                await self.end_game(interaction, "bust")
                return
        else:
            self.player2_hand.append(self.deck.pop())
            if calculate_hand_value(self.player2_hand) > 21:
                await self.end_game(interaction, "bust")
                return

        self.double_down_disabled = True
        self.update_buttons()
        await self.check_for_21()
        if self.game_finished:
            return
        self.current_turn = self.player2 if self.current_turn == self.player1 else self.player1
        embed = await self.update_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=ButtonStyle.green)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.current_turn.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if self.current_turn == self.player1:
            self.current_turn = self.player2
            embed = await self.update_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self.end_game(interaction, "stand")

    @discord.ui.button(label="Double Down", style=ButtonStyle.gray, disabled=True)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.current_turn.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if self.current_turn == self.player1:
            self.player1_hand.append(self.deck.pop())
            if calculate_hand_value(self.player1_hand) > 21:
                await self.end_game(interaction, "bust")
                return
        else:
            self.player2_hand.append(self.deck.pop())
            if calculate_hand_value(self.player2_hand) > 21:
                await self.end_game(interaction, "bust")
                return

        self.double_down_disabled = True
        self.update_buttons()
        await self.end_game(interaction, "double_down")

    async def end_game(self, interaction: Optional[discord.Interaction], reason: str):
        self.game_finished = True
        player1_value = calculate_hand_value(self.player1_hand)
        player2_value = calculate_hand_value(self.player2_hand)

        if reason == "bust":
            if player1_value > 21:
                result = f"{self.player1.mention} busts! {self.player2.mention} wins!"
            else:
                result = f"{self.player2.mention} busts! {self.player1.mention} wins!"
        elif reason == "21":
            if player1_value == 21:
                result = f"{self.player1.mention} wins with 21!"
            else:
                result = f"{self.player2.mention} wins with 21!"
        else:
            if player1_value > player2_value:
                result = f"{self.player1.mention} wins with {player1_value}!"
            elif player2_value > player1_value:
                result = f"{self.player2.mention} wins with {player2_value}!"
            else:
                result = "It's a tie!"

        embed = discord.Embed(
            title="Game Over!",
            description=(
                f"{result}\n\n"
                f"**{self.player1.display_name}'s hand ({player1_value})**\n### {format_hand(self.player1_hand)}\n\n"
                f"**{self.player2.display_name}'s hand ({player2_value})**\n### {format_hand(self.player2_hand)}"
            ),
            color=discord.Color.green(),
        )
        self.disable_all_items()
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            await self.message.edit(embed=embed, view=self)

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True


# ---------- Cookie ----------

class CookieButton(Button):
    def __init__(self):
        super().__init__(style=ButtonStyle.green, emoji="🍪", custom_id="cookie_button")

    async def callback(self, interaction: Interaction):
        view: CookieView = self.view
        if view.winner:
            await interaction.response.send_message(f"{view.winner.mention} clicked the cookie first! 🍪", ephemeral=True)
            return

        view.winner = interaction.user
        for child in view.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.description = f"{interaction.user.mention} clicked the cookie first! 🍪"
        await interaction.response.edit_message(embed=embed, view=view)


class CookieView(View):
    def __init__(self):
        super().__init__(timeout=10)
        self.winner = None
        self.message = None
        self.add_item(CookieButton())

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

        if not self.winner and self.message:
            try:
                embed = discord.Embed(description="No one clicked the cookie. 🍪", color=0x2B2D31)
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


# ---------- Cog ----------

class Games(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.snake_game_sessions = {}

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    @hybrid_group(name="games", description="Minigame related commands")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def games(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @hybrid_command(name="tictactoe", description="Play TicTacToe with a friend")
    @app_commands.describe(player="The user you want to play against")
    async def tictactoe(self, ctx, player: Optional[discord.Member] = None):
        if player and player.id == ctx.author.id:
            await ctx.warn("You can't play against yourself!")
            return

        color = await get_user_color(self.bot, ctx.author.id)
        embed = discord.Embed(
            description=f"{player.mention if player else ''} Click the button to play Tic-Tac-Toe with {ctx.author.mention}!",
            color=color,
        )

        view = TTTInviteView(ctx.author)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @hybrid_command(name="rps", description="Play Rock-Paper-Scissors with a friend")
    async def rps(self, ctx):
        """Play Rock-Paper-Scissors with a friend"""
        view = View()
        view.add_item(RPSAcceptButton(ctx.author, self.bot))
        color = await get_user_color(self.bot, ctx.author.id)
        embed = discord.Embed(description=f"Click the button to play Rock-Paper-Scissors with {ctx.author.mention}", color=color)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @hybrid_command(name="snake", description="Play Snake game")
    @app_commands.describe()
    async def snake(self, ctx):
        """Play Snake game"""
        game_id = str(ctx.author.id)
        self.snake_game_sessions[game_id] = {
            "snake": [{"x": 3, "y": 3}],
            "food": {"x": 4, "y": 4},
            "grid_size": 7,
            "direction": "none",
            "game_over": False,
            "score": 0,
            "author": ctx.author.id,
        }

        content = "-# **Control the snake using the buttons.**"

        color = await get_user_color(self.bot, ctx.author.id)
        embed = self.render_snake_game(game_id)
        embed.color = color
        await ctx.send(content=content, embed=embed, view=self.get_snake_action_view())

    @staticmethod
    async def update_snake_game(interaction: Interaction, direction: str):
        self = interaction.client.get_cog("Games")
        user_id = str(interaction.user.id)
        if user_id not in self.snake_game_sessions:
            await interaction.response.send_message("No snake game found for you.", ephemeral=True)
            return

        game_state = self.snake_game_sessions[user_id]
        if interaction.user.id != game_state["author"]:
            await interaction.response.send_message("You cannot interact with someone else's command.", ephemeral=True)
            return

        if game_state["game_over"]:
            await interaction.response.send_message("The game is over.", ephemeral=True)
            return

        head = game_state["snake"][0]
        new_head = {"x": head["x"], "y": head["y"]}

        if direction == "up":
            new_head["y"] -= 1
        elif direction == "down":
            new_head["y"] += 1
        elif direction == "left":
            new_head["x"] -= 1
        elif direction == "right":
            new_head["x"] += 1

        if (new_head["x"] < 0 or new_head["x"] >= game_state["grid_size"] or
                new_head["y"] < 0 or new_head["y"] >= game_state["grid_size"] or
                any(part["x"] == new_head["x"] and part["y"] == new_head["y"] for part in game_state["snake"])):
            game_state["game_over"] = True
            await interaction.response.edit_message(content=":x: Game Over! :x:", view=None)
            return

        if new_head["x"] == game_state["food"]["x"] and new_head["y"] == game_state["food"]["y"]:
            game_state["snake"].insert(0, new_head)
            game_state["score"] += 1
            self.place_snake_food(game_state)
        else:
            game_state["snake"].insert(0, new_head)
            game_state["snake"].pop()

        await interaction.response.edit_message(embed=self.render_snake_game(user_id), view=self.get_snake_action_view())

    def get_snake_action_view(self):
        view = View()
        view.add_item(SnakeButton("⬆️", "up"))
        view.add_item(SnakeButton("⬅️", "left"))
        view.add_item(SnakeButton("⬇️", "down"))
        view.add_item(SnakeButton("➡️", "right"))
        return view

    def render_snake_game(self, game_id):
        game_state = self.snake_game_sessions[game_id]
        grid_size = game_state["grid_size"]
        grid = [["⬛" for _ in range(grid_size)] for _ in range(grid_size)]

        if game_state["snake"]:
            head = game_state["snake"][0]
            grid[head["y"]][head["x"]] = "🟣"

            for part in game_state["snake"][1:]:
                grid[part["y"]][part["x"]] = "🟨"

        food = game_state["food"]
        grid[food["y"]][food["x"]] = "🍎"

        grid_str = "\n".join("".join(row) for row in grid)

        embed = discord.Embed(title="Snake Game", description=grid_str, color=0x000000)
        embed.add_field(name="Score", value=str(game_state["score"]))
        return embed

    def place_snake_food(self, game_state):
        empty_spaces = [
            {"x": x, "y": y}
            for y in range(game_state["grid_size"])
            for x in range(game_state["grid_size"])
            if not any(part["x"] == x and part["y"] == y for part in game_state["snake"])
        ]
        game_state["food"] = random.choice(empty_spaces)

    @hybrid_command(name="blackjack", description="Play Blackjack with a friend")
    @app_commands.describe()
    async def blackjack(self, ctx):
        """Play Blackjack with a friend"""
        view = View()
        view.add_item(BlackjackButton(ctx.author, self.bot))
        color = await get_user_color(self.bot, ctx.author.id)
        embed = discord.Embed(description=f"Click the button to play Blackjack with {ctx.author.mention}", color=color)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @hybrid_command(name="cookie", description="Click the cookie first")
    @app_commands.describe()
    async def cookie(self, ctx):
        """Click the cookie first"""
        color = await get_user_color(self.bot, ctx.author.id)
        embed = discord.Embed(description="Click the cookie in **5**", color=color)
        message = await ctx.send(embed=embed)

        for i in range(4, 0, -1):
            await asyncio.sleep(1)
            embed = discord.Embed(description=f"Click the cookie in **{i}**", color=color)
            await message.edit(embed=embed)

        await asyncio.sleep(1)
        embed = discord.Embed(description="Click the cookie 🍪", color=color)
        view = CookieView()
        view.message = message
        await message.edit(embed=embed, view=view)