import secrets

def get_multipliers(game: str, **kwargs):
    if game == "crossroad":
        length = kwargs.get("length", 10)

        base = [
            1 + (i * 0.38) + (i ** 1.22 * 0.09)
            for i in range(length)
        ]

        multipliers = []
        for i, v in enumerate(base):
            if i == 1:
                start = 1.25 + (secrets.randbelow(31) / 100)
                value = start
            else:
                rnd = (secrets.randbelow(61) - 30) / 1200
                value = v * (1 + rnd)

            multipliers.append(round(value, 2))

        return multipliers

    if game == "towers":
        rows = kwargs.get("rows", 5)
        base = [1.3 * (1.4 ** i) for i in range(rows)][::-1]
        jitter = kwargs.get("jitter", False)
        if not jitter:
            return [round(v, 2) for v in base]
        values = []
        for v in base:
            rnd = (secrets.randbelow(61) - 30) / 1000
            values.append(round(v * (1 + rnd), 2))
        return values

    if game == "mines":
        clicks = kwargs["clicks"]
        bombs = kwargs["bombs"]
        rows = kwargs["rows"]
        columns = kwargs["columns"]
        safe_tiles = (rows * columns) - bombs
        base = 1.0 + (clicks / safe_tiles) * (bombs * 1.25)
        rnd = (secrets.randbelow(61) - 30) / 1000
        value = base * (1 + rnd)
        return round(value, 2)

    return []
