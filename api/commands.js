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
      const body = await req.json();

      if (!body || !Array.isArray(body.categories)) {
        return res.status(400).json({ error: "Invalid payload: categories array required" });
      }

      for (const category of body.categories) {
        if (!category.name || !Array.isArray(category.commands)) {
          return res.status(400).json({ error: "Invalid category structure" });
        }
        for (const cmd of category.commands) {
          if (!validateCommand(cmd)) {
            return res.status(400).json({ error: `Invalid command structure: ${cmd.name}` });
          }
        }
      }

      commandsCache = {
        categories: body.categories,
        totalCommands: body.totalCommands || body.categories.reduce((sum, cat) => sum + cat.commands.length, 0),
      };

      return res.status(200).json({ success: true, totalCommands: commandsCache.totalCommands });
    } catch (error) {
      return res.status(400).json({ error: "Invalid JSON body" });
    }
  }

  return res.status(405).json({ error: "Method not allowed" });
}
