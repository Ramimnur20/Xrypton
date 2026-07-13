let commandsCache = null;

const validateCommand = (cmd) => {
  if (!cmd || typeof cmd.name !== "string") return false;
  if (!Array.isArray(cmd.arguments)) return false;
  return true;
};

export default async function handler(req, res) {
  if (req.method === "GET") {
    if (!commandsCache) {
      return res.status(404).json({ error: "Commands not synced yet" });
    }
    return res.status(200).json(commandsCache);
  }

  if (req.method === "POST") {
    try {
      const chunks = [];
      for await (const chunk of req) {
        chunks.push(chunk);
      }
      const raw = Buffer.concat(chunks).toString("utf-8");
      const body = raw ? JSON.parse(raw) : {};

      if (!body || !Array.isArray(body.categories)) {
        return res.status(400).json({ error: "Invalid payload: categories array required", received: body });
      }

      for (const category of body.categories) {
        if (!category.name || !Array.isArray(category.commands)) {
          return res.status(400).json({ error: "Invalid category structure", category });
        }
        for (const cmd of category.commands) {
          if (!validateCommand(cmd)) {
            return res.status(400).json({ error: `Invalid command structure: ${cmd.name}`, cmd });
          }
        }
      }

      commandsCache = {
        categories: body.categories,
        totalCommands: body.totalCommands || body.categories.reduce((sum, cat) => sum + cat.commands.length, 0),
      };

      return res.status(200).json({ success: true, totalCommands: commandsCache.totalCommands });
    } catch (error) {
      return res.status(400).json({ error: "Invalid JSON body", details: error.message });
    }
  }

  return res.status(405).json({ error: "Method not allowed" });
}
