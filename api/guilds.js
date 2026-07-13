const BOT_TOKEN = process.env.BOT_TOKEN;

const CACHE_TTL = 60000;
let guildCache = null;
let cacheTimestamp = 0;

export default async function handler(req, res) {
  if (!BOT_TOKEN) {
    return res.status(500).json({ error: 'BOT_TOKEN environment variable is not set' });
  }

  const headers = {
    Authorization: `Bot ${BOT_TOKEN}`,
    'Content-Type': 'application/json',
  };

  const fetchGuilds = async () => {
    const response = await fetch('https://discord.com/api/v10/users/@me/guilds?with_counts=true', { headers });

    if (!response.ok) {
      const errorText = await response.text();
      const error = new Error('Failed to fetch guilds');
      error.status = response.status;
      error.details = errorText;
      throw error;
    }

    return response.json();
  };

  if (req.method === 'POST') {
    try {
      const guilds = await fetchGuilds();
      guildCache = guilds;
      cacheTimestamp = Date.now();

      return res.status(200).json({ success: true, guilds, fetchedAt: new Date().toISOString() });
    } catch (error) {
      return res.status(error.status || 500).json({
        error: 'Failed to fetch guilds',
        details: error.details || error.message,
      });
    }
  }

  if (req.method === 'GET') {
    try {
      if (guildCache && Date.now() - cacheTimestamp < CACHE_TTL) {
        return res.status(200).json({ guilds: guildCache, cached: true, fetchedAt: new Date(cacheTimestamp).toISOString() });
      }

      const guilds = await fetchGuilds();
      guildCache = guilds;
      cacheTimestamp = Date.now();

      return res.status(200).json({ guilds, cached: false, fetchedAt: new Date().toISOString() });
    } catch (error) {
      return res.status(error.status || 500).json({
        error: 'Failed to fetch guilds',
        details: error.details || error.message,
      });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
}
