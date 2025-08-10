from base.bleed import Bot
from base.config import CLIENT
import asyncio
from flask import Flask, jsonify
from flask_cors import CORS
import threading
from flask_socketio import SocketIO
import time

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
bot = Bot()

# kars was here fr on gang on diddy


@app.route("/stats", methods=["GET"])
def stats():
    members = sum(guild.member_count for guild in bot.guilds)
    servers = len(bot.guilds)
    return jsonify({"members": members, "servers": servers})


@socketio.on("connect")
def handle_connect():
    socketio.emit("status_update", get_shard_status())


@socketio.on("disconnect")
def handle_disconnect():
    pass


def get_shard_status():
    shards = []
    for shard_id, shard in bot.shards.items():
        latency = shard.latency * 1000
        shards.append(
            {
                "shard_id": shard_id,
                "is_ready": not shard.is_ws_ratelimited(),
                "server_count": sum(
                    1 for guild in bot.guilds if guild.shard_id == shard_id
                ),
                "cached_user_count": sum(
                    len(guild.members)
                    for guild in bot.guilds
                    if guild.shard_id == shard_id
                ),
                "uptime": bot._uptime,
                "latency": round(latency, 2),
            }
        )
    return {"shards": shards}


def send_status_updates():
    while True:
        socketio.emit("status_update", get_shard_status())
        time.sleep(10)


@app.route("/status", methods=["GET"])
def status():
    shards = []
    for shard_id, shard in bot.shards.items():
        latency = shard.latency * 1000
        shards.append(
            {
                "shard_id": shard_id,
                "is_ready": not shard.is_ws_ratelimited(),
                "server_count": sum(
                    1 for guild in bot.guilds if guild.shard_id == shard_id
                ),
                "cached_user_count": sum(
                    len(guild.members)
                    for guild in bot.guilds
                    if guild.shard_id == shard_id
                ),
                "uptime": bot._uptime,
                "latency": round(latency, 2),
            }
        )
    return jsonify({"shards": shards})


@app.route("/shards", methods=["GET"])
def shards_route():
    shard_data = {}

    if bot.is_ready() and bot.shard_count is not None:
        for shard_id in range(bot.shard_count):
            shard_guilds = [
                str(guild.id) for guild in bot.guilds if guild.shard_id == shard_id
            ]
            shard_data[str(shard_id)] = shard_guilds

    return jsonify(shard_data)


@app.route("/commands", methods=["GET"])
def commands_route():
    commands_data = {}

    for command in bot.commands:
        category = command.cog_name if command.cog_name else "Uncategorized"

        if category in ["Jishaku", "Owner"]:
            continue

        if category not in commands_data:
            commands_data[category] = []

        command_data = {
            "name": command.name,
            "description": command.description if command.description else "None",
            "category": category,
            "args": command.parameters if command.parameters else "None",
            "permissions": command.permissions if command.permissions else "None",
        }

        if hasattr(command, "commands") and command.commands:
            for subcommand in command.commands:
                subcommand_category = (
                    subcommand.cog_name if subcommand.cog_name else "Uncategorized"
                )

                if subcommand_category in ["Jishaku", "Owner"]:
                    continue

                commands_data[category].append(
                    {
                        "name": f"{command.name} {subcommand.name}",
                        "description": (
                            subcommand.description if subcommand.description else "None"
                        ),
                        "category": category,
                        "args": (
                            subcommand.parameters if subcommand.parameters else "None"
                        ),
                        "permissions": (
                            subcommand.permissions if subcommand.permissions else "None"
                        ),
                    }
                )

        commands_data[category].append(command_data)

    return jsonify(commands_data)


async def run_bot():
    global bot
    bot = Bot()
    await bot.start(token=CLIENT.TOKEN)


def run_flask():
    app.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
    bot_thread.start()

    run_flask()
