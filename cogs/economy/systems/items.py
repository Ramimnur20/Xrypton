ITEMS = {
    # tools and shit
    "fishing_rod": {
        "name": "Fishing Rod",
        "emoji": "<a:eco_fishingrod:1439036464858923341>",
        "price": 15000,
        "sell_price": 7500,
        "type": "tool",
        "usable": False,
    },
    "fish_bag": {
        "name": "Fish Bag",
        "emoji": "<:eco_fishbag:1439036479048257708>",
        "price": 50000,
        "sell_price": 25000,
        "type": "storage",
        "usable": False,
        "capacity": 9999999,
    },

    # common
    "salmon":        {"name": "Salmon",              "emoji": "🐟", "value": 500,   "type": "fish", "rarity": "common"},
    "carp":          {"name": "Carp",                "emoji": "🐠", "value": 200,   "type": "fish", "rarity": "common"},
    "anchovy":       {"name": "Anchovy",             "emoji": "🐟", "value": 150,   "type": "fish", "rarity": "common"},
    "bluefish":      {"name": "Bluefish",            "emoji": "🐟", "value": 350,   "type": "fish", "rarity": "common"},
    "catfish":       {"name": "Catfish",             "emoji": "🐱", "value": 300,   "type": "fish", "rarity": "common"},
    "shrimp":        {"name": "Shrimp",              "emoji": "🦐", "value": 250,   "type": "fish", "rarity": "common"},
    "sardine":       {"name": "Sardine",             "emoji": "🐟", "value": 180,   "type": "fish", "rarity": "common"},
    "perch":         {"name": "Perch",               "emoji": "🐠", "value": 240,   "type": "fish", "rarity": "common"},
    "herring":       {"name": "Herring",             "emoji": "🐟", "value": 210,   "type": "fish", "rarity": "common"},
    "mackerel":      {"name": "Mackerel",            "emoji": "🐟", "value": 260,   "type": "fish", "rarity": "common"},
    "goby":          {"name": "Goby",                "emoji": "🐠", "value": 230,   "type": "fish", "rarity": "common"},
    "tilapia":       {"name": "Tilapia",             "emoji": "🐟", "value": 270,   "type": "fish", "rarity": "common"},
    "minnow":        {"name": "Minnow",              "emoji": "🐟", "value": 100,   "type": "fish", "rarity": "common"},
    "cod":           {"name": "Cod",                 "emoji": "🐟", "value": 380,   "type": "fish", "rarity": "common"},
    "sunfish":       {"name": "Sunfish",             "emoji": "🐠", "value": 320,   "type": "fish", "rarity": "common"},
    "eel_small":     {"name": "River Eel",           "emoji": "🪱", "value": 290,   "type": "fish", "rarity": "common"},
    "snail":         {"name": "Sea Snail",           "emoji": "🐌", "value": 220,   "type": "fish", "rarity": "common"},
    "clam_small":    {"name": "Clam",                "emoji": "🐚", "value": 200,   "type": "fish", "rarity": "common"},
    "urchin":        {"name": "Sea Urchin",          "emoji": "🦔", "value": 230,   "type": "fish", "rarity": "common"},
    "jelly_small":   {"name": "Small Jellyfish",     "emoji": "🪼", "value": 350,   "type": "fish", "rarity": "common"},

    # uncommon
    "squid":         {"name": "Squid",               "emoji": "🦑", "value": 1500,  "type": "fish", "rarity": "uncommon"},
    "crab":          {"name": "Crab",                "emoji": "🦀", "value": 900,   "type": "fish", "rarity": "uncommon"},
    "blowfish":      {"name": "Blowfish",            "emoji": "🐡", "value": 1800,  "type": "fish", "rarity": "uncommon"},
    "rainbow":       {"name": "Rainbow Trout",       "emoji": "🐠", "value": 1400,  "type": "fish", "rarity": "uncommon"},
    "oyster":        {"name": "Oyster",              "emoji": "🐚", "value": 1300,  "type": "fish", "rarity": "uncommon"},
    "lobster_small": {"name": "Small Lobster",       "emoji": "🦞", "value": 1100,  "type": "fish", "rarity": "uncommon"},
    "octopus_small": {"name": "Small Octopus",       "emoji": "🐙", "value": 1700,  "type": "fish", "rarity": "uncommon"},
    "crayfish":      {"name": "Crayfish",            "emoji": "🦞", "value": 1000,  "type": "fish", "rarity": "uncommon"},
    "turtle_baby":   {"name": "Baby Turtle",         "emoji": "🐢", "value": 1600,  "type": "fish", "rarity": "uncommon"},
    "squid_ink":     {"name": "Ink Squid",           "emoji": "🦑", "value": 1450,  "type": "fish", "rarity": "uncommon"},

    # rare
    "lobster":       {"name": "Lobster",             "emoji": "🦞", "value": 5000,  "type": "fish", "rarity": "rare"},
    "octopus":       {"name": "Octopus",             "emoji": "🐙", "value": 4200,  "type": "fish", "rarity": "rare"},
    "tropical":      {"name": "Tropical Fish",       "emoji": "🐠", "value": 3800,  "type": "fish", "rarity": "rare"},
    "seahorse":      {"name": "Seahorse",            "emoji": "🦄", "value": 3500,  "type": "fish", "rarity": "rare"},
    "prawn":         {"name": "Prawn",               "emoji": "🦐", "value": 3600,  "type": "fish", "rarity": "rare"},
    "jelly":         {"name": "Jellyfish",           "emoji": "🪼", "value": 4600,  "type": "fish", "rarity": "rare"},
    "turtle":        {"name": "Sea Turtle",          "emoji": "🐢", "value": 5200,  "type": "fish", "rarity": "rare"},
    "starfish":      {"name": "Starfish",            "emoji": "⭐",  "value": 4000,  "type": "fish", "rarity": "rare"},
    "crystal_clam":  {"name": "Crystal Clam",        "emoji": "🐚", "value": 4800,  "type": "fish", "rarity": "rare"},

    # mythic
    "golden_fish":   {"name": "Golden Fish",         "emoji": "🐟", "value": 7500,   "type": "fish", "rarity": "mythic"},
    "mythic_koi":    {"name": "Mythic Koi",          "emoji": "🐠", "value": 15000,  "type": "fish", "rarity": "mythic"},
    "shark":         {"name": "Shark",               "emoji": "🦈", "value": 20000,  "type": "fish", "rarity": "mythic"},
    "stingray":      {"name": "Stingray",            "emoji": "🪸", "value": 10000,  "type": "fish", "rarity": "mythic"},
    "leviathan":     {"name": "Leviathan Scale",     "emoji": "🐉", "value": 25000,  "type": "fish", "rarity": "mythic"},
    "void_jelly":    {"name": "Void Jellyfish",      "emoji": "🪼", "value": 18000,  "type": "fish", "rarity": "mythic"},
    "krakenling":    {"name": "Krakenling",          "emoji": "🦑", "value": 24000,  "type": "fish", "rarity": "mythic"},
    "phoenix_fish":  {"name": "Phoenix Fish",        "emoji": "🔥", "value": 30000,  "type": "fish", "rarity": "mythic"},
}

RARITY_WEIGHT = {
    "common": 70,
    "uncommon": 20,
    "rare": 8,
    "mythic": 2,
}

def get_items_by_type(type_name: str):
    return {k: v for k, v in ITEMS.items() if v.get("type") == type_name}

def get_fish_items():
    return get_items_by_type("fish")

def get_shop_items():
    return {k: v for k, v in ITEMS.items() if "price" in v}

def get_sellable_items():
    return {k: v for k, v in ITEMS.items() if "sell_price" in v}

__all__ = ["ITEMS", "RARITY_WEIGHT", "get_items_by_type", "get_fish_items", "get_shop_items", "get_sellable_items"]
