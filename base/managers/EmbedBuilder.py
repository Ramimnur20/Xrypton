import sys, os, discord
from discord.ext import commands
from typing import Union


class EmbedBuilder:
    def ordinal(self, num: int) -> str:
        """Convert from number to ordinal (10 - 10th)"""
        numb = str(num)
        if numb.startswith("0"):
            numb = numb.strip("0")
        if numb in ["11", "12", "13"]:
            return numb + "th"
        if numb.endswith("1"):
            return numb + "st"
        elif numb.endswith("2"):
            return numb + "nd"
        elif numb.endswith("3"):
            return numb + "rd"
        else:
            return numb + "th"

    def get_parts(params):  # type: ignore
        params = params.replace("{embed}", "")  # type: ignore
        return [p[1:][:-1] for p in params.split("$v")]

    def embed_replacement(user: discord.Member, params: str = None):  # type: ignore
        if params is None:
            return None
        if "{user}" in params:
            params = params.replace(
                "{user}", str(user.name) + "#" + str(user.discriminator)
            )
        if "{user.mention}" in params:
            params = params.replace("{user.mention}", user.mention)
        if "{user.name}" in params:
            params = params.replace("{user.name}", user.name)
        if "{user.avatar}" in params:
            params = params.replace("{user.avatar}", str(user.display_avatar.url))
        if "{user.joined_at}" in params:
            params = params.replace(
                "{user.joined_at}",
                discord.utils.format_dt(user.joined_at, style="R"),  # type: ignore
            )
        if "{user.created_at}" in params:
            params = params.replace(
                "{user.created_at}", discord.utils.format_dt(user.created_at, style="R")
            )
        if "{user.discriminator}" in params:
            params = params.replace("{user.discriminator}", user.discriminator)
        if "{guild.name}" in params:
            params = params.replace("{guild.name}", user.guild.name)
        if "{guild.count}" in params:
            params = params.replace("{guild.count}", str(user.guild.member_count))
        if "{guild.count.format}" in params:
            params = params.replace(
                "{guild.count.format}",
                EmbedBuilder.ordinal(len(user.guild.members)),  # type: ignore
            )
        if "{guild.id}" in params:
            params = params.replace("{guild.id}", user.guild.id)  # type: ignore
        if "{guild.created_at}" in params:
            params = params.replace(
                "{guild.created_at}",
                discord.utils.format_dt(user.guild.created_at, style="R"),
            )
        if "{guild.boost_count}" in params:
            params = params.replace(
                "{guild.boost_count}", str(user.guild.premium_subscription_count)
            )
        if "{guild.booster_count}" in params:
            params = params.replace(
                "{guild.booster_count}", str(len(user.guild.premium_subscribers))
            )
        if "{guild.boost_count.format}" in params:
            params = params.replace(
                "{guild.boost_count.format}",
                EmbedBuilder.ordinal(user.guild.premium_subscription_count),  # type: ignore
            )
        if "{guild.booster_count.format}" in params:
            params = params.replace(
                "{guild.booster_count.format}",
                EmbedBuilder.ordinal(len(user.guild.premium_subscribers)),  # type: ignore
            )
        if "{guild.boost_tier}" in params:
            params = params.replace("{guild.boost_tier}", str(user.guild.premium_tier))
        if "{guild.vanity}" in params:
            params = params.replace(
                "{guild.vanity}",
                "/" + user.guild.vanity_url_code or "none",  # type: ignore
            )
        if "{invisible}" in params:
            params = params.replace("{invisible}", "2B2D31")
        if "{botcolor}" in params:
            params = params.replace("{botcolor}", "7d7ead")
        if "{guild.icon}" in params:
            if user.guild.icon:
                params = params.replace("{guild.icon}", user.guild.icon.url)
            else:
                params = params.replace("{guild.icon}", "https://none.none")

        return params

    async def to_object(params):  # type: ignore
        x = {}
        fields = []
        content = None
        view = discord.ui.View()

        for part in EmbedBuilder.get_parts(params):
            if part.startswith("content:"):
                content = part[len("content:") :]

            if part.startswith("title:"):
                x["title"] = part[len("title:") :]

            if part.startswith("description:"):
                x["description"] = part[len("description:") :]

            if part.startswith("color:"):
                try:
                    x["color"] = int(part[len("color:") :].replace("#", ""), 16)
                except:
                    x["color"] = 0x2F3136

            if part.startswith("image:"):
                x["image"] = {"url": part[len("image:") :]}

            if part.startswith("thumbnail:"):
                x["thumbnail"] = {"url": part[len("thumbnail:") :]}

            if part.startswith("author:"):
                z = part[len("author:") :].split(" && ")
                try:
                    name = z[0] if z[0] else None
                except:
                    name = None
                try:
                    icon_url = z[1] if z[1] else None
                except:
                    icon_url = None
                try:
                    url = z[2] if z[2] else None
                except:
                    url = None

                x["author"] = {"name": name}
                if icon_url:
                    x["author"]["icon_url"] = icon_url
                if url:
                    x["author"]["url"] = url

            if part.startswith("field:"):
                z = part[len("field:") :].split(" && ")
                try:
                    name = z[0] if z[0] else None
                except:
                    name = None
                try:
                    value = z[1] if z[1] else None
                except:
                    value = None
                try:
                    inline = z[2] if z[2] else True
                except:
                    inline = True

                if isinstance(inline, str):
                    if inline == "true":
                        inline = True

                    elif inline == "false":
                        inline = False

                fields.append({"name": name, "value": value, "inline": inline})

            if part.startswith("footer:"):
                z = part[len("footer:") :].split(" && ")
                try:
                    text = z[0] if z[0] else None
                except:
                    text = None
                try:
                    icon_url = z[1] if z[1] else None
                except:
                    icon_url = None
                x["footer"] = {"text": text}
                if icon_url:
                    x["footer"]["icon_url"] = icon_url

            if part.startswith("button:"):
                z = part[len("button:") :].split(" && ")
                disabled = True
                style = discord.ButtonStyle.gray
                emoji = None
                label = None
                url = None
                for m in z:
                    if "label:" in m:
                        label = m.replace("label:", "")
                    if "url:" in m:
                        url = m.replace("url:", "").strip()
                        disabled = False
                    if "emoji:" in m:
                        emoji = m.replace("emoji:", "").strip()
                    if "disabled" in m:
                        disabled = True
                    if "style:" in m:
                        if m.replace("style:", "").strip() == "red":
                            style = discord.ButtonStyle.red
                        elif m.replace("style:", "").strip() == "green":
                            style = discord.ButtonStyle.green
                        elif m.replace("style:", "").strip() == "gray":
                            style = discord.ButtonStyle.gray
                        elif m.replace("style:", "").strip() == "blue":
                            style = discord.ButtonStyle.blurple

                view.add_item(
                    discord.ui.Button(
                        style=style,
                        label=label,
                        emoji=emoji,
                        url=url,
                        disabled=disabled,
                    )
                )

        if not x:
            embed = None
        else:
            x["fields"] = fields
            embed = discord.Embed.from_dict(x)
        return content, embed, view


class EmbedScript(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str):
        x = await EmbedBuilder.to_object(
            EmbedBuilder.embed_replacement(ctx.author, argument)  # type: ignore
        )
        if x[0] or x[1]:
            return {"content": x[0], "embed": x[1], "view": x[2]}
        return {"content": EmbedBuilder.embed_replacement(ctx.author, argument)}  # type: ignore

async def send_embed(destination, message, member):
    processed_message = EmbedBuilder.embed_replacement(member, message)  # type: ignore
    content, embed, view = await EmbedBuilder.to_object(processed_message)
    await destination.send(
        content=content or processed_message,
        embed=embed,
        view=view if content or embed else None,
    )