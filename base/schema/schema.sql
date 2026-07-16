CREATE TABLE IF NOT EXISTS prefix (
    guild_id INTEGER PRIMARY KEY,
    prefix TEXT
);

CREATE TABLE IF NOT EXISTS lost_boosters (
    guild_id INTEGER,
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    discriminator TEXT,
    lost_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid (
    guild_id INTEGER,
    command TEXT,
    punishment TEXT,
    seconds INTEGER
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id INTEGER,
    module TEXT,
    object_id INTEGER,
    mode TEXT
);

CREATE TABLE IF NOT EXISTS guild_whitelist (
    guild_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS afk (
    user_id INTEGER PRIMARY KEY,
    status TEXT,
    time INTEGER
);

CREATE TABLE IF NOT EXISTS forcenick (
    guild_id INTEGER,
    user_id INTEGER,
    name TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS lockdown (
    guild_id INTEGER,
    channel_id INTEGER,
    role_id INTEGER
);

CREATE TABLE IF NOT EXISTS welcome (
    guild_id INTEGER,
    channel_id INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS boost (
    guild_id INTEGER,
    channel_id INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS warnings (
    guild_id INTEGER,
    user_id INTEGER,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY(guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS aliases (
    guild_id INTEGER,
    alias TEXT,
    command TEXT,
    invoke TEXT,
    PRIMARY KEY (guild_id, alias)
);

CREATE TABLE IF NOT EXISTS autorole (
    guild_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER,
    message TEXT,
    schedule TEXT,
    PRIMARY KEY (guild_id, channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS autoresponders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT NOT NULL,
    not_strict INTEGER DEFAULT 0,
    self_destruct INTEGER DEFAULT 0,
    self_destruct_time INTEGER DEFAULT 0,
    delete_trigger INTEGER DEFAULT 0,
    reply INTEGER DEFAULT 0,
    UNIQUE(guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS booster_module (
    guild_id INTEGER PRIMARY KEY,
    base INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS booster_roles (
    guild_id INTEGER,
    user_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS br_award (
    guild_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS leave (
    guild_id INTEGER,
    channel_id INTEGER,
    message TEXT,
    PRIMARY KEY(guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS fake_permissions (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS giveaway (
    guild_id INTEGER,
    user_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER PRIMARY KEY,
    prize TEXT,
    emoji TEXT,
    winners INTEGER,
    ends_at DATETIME,
    ended INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    message_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS ancfg (
    guild_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS antinuke_modules (
    guild_id INTEGER,
    module TEXT,
    punishment TEXT,
    threshold INTEGER,
    toggled INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, module)
);

CREATE TABLE IF NOT EXISTS antinuke_admins (
    guild_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS antinuke_whitelist (
    guild_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy (
    user_id INTEGER PRIMARY KEY,
    money INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    bank_limit INTEGER DEFAULT 100000,
    last_daily TIMESTAMP,
    daily_streak INTEGER DEFAULT 0,
    claimed_bonus TIMESTAMP,
    premium_monthly TIMESTAMP,
    join_bonus_claimed INTEGER DEFAULT 0,
    last_fish TIMESTAMP
);

CREATE TABLE IF NOT EXISTS economy_stats (
    user_id INTEGER PRIMARY KEY,
    total_games INTEGER DEFAULT 0,
    total_wins INTEGER DEFAULT 0,
    total_losses INTEGER DEFAULT 0,
    total_ties INTEGER DEFAULT 0,
    total_won INTEGER DEFAULT 0,
    total_lost INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS economy_game_stats (
    user_id INTEGER,
    game TEXT,
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    ties INTEGER DEFAULT 0,
    won INTEGER DEFAULT 0,
    lost INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, game)
);

CREATE TABLE IF NOT EXISTS economy_inventory (
    user_id INTEGER,
    item_id TEXT,
    amount INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS economy_fishbag (
    user_id INTEGER PRIMARY KEY,
    fish TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS wallet_settings (
    user_id INTEGER PRIMARY KEY,
    embed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wallet_colors (
    user_id INTEGER PRIMARY KEY,
    primary_color INTEGER,
    secondary_color INTEGER
);

CREATE TABLE IF NOT EXISTS configuration (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    category_id INTEGER,
    bitrate INTEGER,
    region TEXT,
    role_id INTEGER
);

CREATE TABLE IF NOT EXISTS channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL
);
