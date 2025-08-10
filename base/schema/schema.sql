CREATE TABLE IF NOT EXISTS prefix (
    guild_id BIGINT PRIMARY KEY,
    prefix VARCHAR(7)
);

CREATE TABLE IF NOT EXISTS lost_boosters (
    guild_id BIGINT,
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    discriminator TEXT,
    lost_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid (
    guild_id BIGINT, 
    command TEXT, 
    punishment TEXT, 
    seconds INTEGER
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id BIGINT, 
    module TEXT, 
    object_id BIGINT, 
    mode TEXT
);

CREATE TABLE IF NOT EXISTS guild_whitelist (
    guild_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS afk (
    user_id BIGINT PRIMARY KEY,
    status TEXT,
    time BIGINT
);

CREATE TABLE IF NOT EXISTS forcenick (
    guild_id BIGINT, 
    user_id BIGINT, 
    name TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS lockdown (
    guild_id BIGINT,
    channel_id BIGINT,
    role_id BIGINT
);

CREATE TABLE IF NOT EXISTS welcome (
    guild_id BIGINT,
    channel_id BIGINT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS boost (
    guild_id BIGINT,
    channel_id BIGINT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS warnings (
    guild_id BIGINT,
    user_id BIGINT,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY(guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS aliases (
    guild_id BIGINT,
    alias TEXT,
    command TEXT,
    invoke TEXT,
    PRIMARY KEY (guild_id, alias)
);

CREATE TABLE IF NOT EXISTS autorole (
    guild_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS sticky_messages (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    message TEXT,
    schedule TEXT,
    PRIMARY KEY (guild_id, channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS autoresponders (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT NOT NULL,
    not_strict BOOLEAN DEFAULT FALSE,
    self_destruct BOOLEAN DEFAULT FALSE,
    self_destruct_time INT DEFAULT 0, 
    delete_trigger BOOLEAN DEFAULT FALSE,
    reply BOOLEAN DEFAULT FALSE,
    UNIQUE(guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS booster_module (
    guild_id BIGINT PRIMARY KEY,  
    base BIGINT DEFAULT NULL      
);


CREATE TABLE IF NOT EXISTS booster_roles (
    guild_id BIGINT,
    user_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, user_id)  
);


CREATE TABLE IF NOT EXISTS br_award (
    guild_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)  
);

CREATE TABLE IF NOT EXISTS leave (
    guild_id BIGINT,
    channel_id BIGINT,
    message TEXT,
    PRIMARY KEY(guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS fake_permissions (
    guild_id bigint NOT NULL,
    role_id bigint NOT NULL,
    permission text NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);
