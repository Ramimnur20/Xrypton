import asyncio
import io
import base64
import aiohttp
from cogs.economy.ecoutils.framework.discord.decorators import check_donor

try:
    from PIL import Image, ImageDraw, ImageFont

    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def _load_font(size: int):
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


async def generate_wallet(bot, user, money, bank):
    """Generate a wallet card image. Returns a BytesIO buffer, or ``None`` if
    PIL is unavailable (caller should fall back to a text/embed response)."""
    if not _HAS_PIL:
        return None

    async with bot.pool.acquire() as conn:
        bank_limit = (
            await conn.fetchval("SELECT bank_limit FROM economy WHERE user_id=$1", user.id)
            or 0
        )
        row = await conn.fetchrow(
            "SELECT primary_color, secondary_color FROM wallet_colors WHERE user_id=$1",
            user.id,
        )

    donor = await check_donor(bot, user.id)

    redis_key = f"utils:avatar:{user.id}"
    cached = await bot.redis.get(redis_key)
    avatar_bytes = None
    if cached:
        try:
            avatar_bytes = base64.b64decode(cached)
        except Exception:
            avatar_bytes = None
    if avatar_bytes is None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(user.display_avatar.url) as resp:
                    avatar_bytes = await asyncio.wait_for(resp.read(), timeout=5)
            await bot.redis.set(
                redis_key, base64.b64encode(avatar_bytes).decode(), ex=30
            )
        except Exception:
            avatar_bytes = None

    def _generate_sync():
        scale = 2
        cwidth, cheight = 381, 249

        if row and row["primary_color"] is not None:
            start_color = row["primary_color"] or 0x0A50F0
            end_color = row["secondary_color"] or 0x3278FA
        else:
            start_color, end_color = (
                (0x0A50F0, 0x3278FA) if not donor else (0x0F0F0F, 0x2A2A2A)
            )

        sr, sg, sb = (
            (start_color >> 16) & 255,
            (start_color >> 8) & 255,
            start_color & 255,
        )
        er, eg, eb = (
            (end_color >> 16) & 255,
            (end_color >> 8) & 255,
            end_color & 255,
        )

        w, h = int(cwidth * scale), int(cheight * scale)
        grad = Image.new("RGBA", (w, h))
        gdraw = ImageDraw.Draw(grad)

        for y in range(h):
            r = int(sr + (er - sr) * (y / h))
            g = int(sg + (eg - sg) * (y / h))
            b = int(sb + (eb - sb) * (y / h))
            gdraw.line([(0, y), (w, y)], fill=(r, g, b))

        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, w, h), radius=int(26 * scale), fill=255
        )
        card = Image.composite(grad, Image.new("RGBA", (w, h)), mask)

        font_big = _load_font(int(35 * scale))
        font_small = _load_font(int(18 * scale))
        font_user = _load_font(int(12 * scale))

        avg_brightness = (sum([sr + sg + sb, er + eg + eb]) / 6) / 255
        light_theme = avg_brightness > 0.55
        text_color = (30, 30, 30) if light_theme else (255, 255, 255)

        draw = ImageDraw.Draw(card)

        draw.text((int(20 * scale), int(20 * scale)), "Xrypton", font=font_big, fill=text_color)

        title = "premium" if donor else "standard"
        title_w = draw.textbbox((0, 0), title, font=font_small)[2]
        draw.text(
            (w - title_w - int(20 * scale), int(20 * scale)),
            title,
            font=font_small,
            fill=text_color,
        )

        y1 = int(90 * scale)
        y2 = int(120 * scale)
        y3 = int(150 * scale)

        draw.text((int(44 * scale), y1), f"${money:,}", font=font_small, fill=text_color)
        draw.text(
            (int(44 * scale), y2),
            f"${bank:,} / ${bank_limit:,}",
            font=font_small,
            fill=text_color,
        )
        draw.text((int(44 * scale), y3), "0 stars", font=font_small, fill=text_color)

        if avatar_bytes:
            try:
                avatar_size = int(29 * scale)
                avatar = (
                    Image.open(io.BytesIO(avatar_bytes))
                    .convert("RGBA")
                    .resize((avatar_size, avatar_size), Image.BILINEAR)
                )
                mask_avatar = Image.new("L", (avatar_size, avatar_size), 0)
                ImageDraw.Draw(mask_avatar).ellipse(
                    (0, 0, avatar_size, avatar_size), fill=255
                )
                avatar_x = int(17 * scale)
                avatar_y = int(cheight * scale - 44 * scale)
                card.paste(avatar, (avatar_x, avatar_y), mask_avatar)
                draw.text(
                    (int(avatar_x + 38 * scale), int(avatar_y + 8 * scale)),
                    user.name[:18].upper(),
                    font=font_user,
                    fill=text_color,
                )
            except Exception:
                pass

        card = card.resize((cwidth, cheight), Image.BILINEAR)

        buf = io.BytesIO()
        card.save(buf, "PNG")
        buf.seek(0)
        return buf

    return await asyncio.to_thread(_generate_sync)
