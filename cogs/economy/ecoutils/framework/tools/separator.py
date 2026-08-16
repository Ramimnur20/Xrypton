import io

try:
    from PIL import Image, ImageDraw

    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def _blank_png() -> bytes:
    if not _HAS_PIL:
        # 1x1 transparent PNG fallback
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
            b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT"
            b"\x08\x1d\x01\x01\x00\xfe\xff\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf.read()


async def makeseparator(bot, user_id: int) -> bytes:
    """Generate a decorative separator image used as an embed footer image."""
    if not _HAS_PIL:
        return _blank_png()

    def _render() -> bytes:
        width, height = 500, 8
        start = (0x0A, 0x50, 0xF0)
        end = (0x32, 0x78, 0xFA)
        img = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(img)
        for x in range(width):
            t = x / width
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            draw.line([(x, 0), (x, height)], fill=(r, g, b, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf.read()

    import asyncio

    return await asyncio.to_thread(_render)
