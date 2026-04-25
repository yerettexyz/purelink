import threading
import asyncio
import discord
import os
import json
import time

from discord import app_commands

# --- Non-Invasive Guard & Slash Commands ---
IGNORE_FILE = 'ignore.json'
original_dispatch = discord.Client.dispatch
COMMANDS_SYNCED = False

async def setup_real_slash_commands(bot):
    global COMMANDS_SYNCED
    if COMMANDS_SYNCED: return
    
    if not hasattr(bot, 'tree'):
        bot.tree = app_commands.CommandTree(bot)

    @bot.tree.command(name="purelink_help", description="Show Purelink plugin help")
    async def help_cmd(interaction: discord.Interaction):
        help_text = (
            "💡 **Purelink Plugin Help**\n"
            "`/ignore_channel <id>` - Stop bot from cleaning links in a channel\n"
            "`/ignore_user <id>` - Stop bot from cleaning links for a user\n"
            "-# *Native Slash Commands System*"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

    @bot.tree.command(name="ignore_channel", description="Add a channel to the ignore list")
    @app_commands.describe(channel_id="The ID of the channel to ignore")
    async def ignore_channel(interaction: discord.Interaction, channel_id: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        
        try:
            with open(IGNORE_FILE, 'r') as f: data = json.load(f)
            data.setdefault('ignored_channels', []).append(int(channel_id))
            data['ignored_channels'] = list(set(data['ignored_channels']))
            with open(IGNORE_FILE, 'w') as f: json.dump(data, f, indent=4)
            await interaction.response.send_message(f"✅ Channel `{channel_id}` ignored.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @bot.tree.command(name="ignore_user", description="Add a user to the ignore list")
    @app_commands.describe(user_id="The ID of the user to ignore")
    async def ignore_user(interaction: discord.Interaction, user_id: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        
        try:
            with open(IGNORE_FILE, 'r') as f: data = json.load(f)
            data.setdefault('ignored_users', []).append(int(user_id))
            data['ignored_users'] = list(set(data['ignored_users']))
            with open(IGNORE_FILE, 'w') as f: json.dump(data, f, indent=4)
            await interaction.response.send_message(f"✅ User `{user_id}` ignored.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    try:
        await bot.tree.sync()
        COMMANDS_SYNCED = True
        print("[PLUGIN] Native Slash Commands synced successfully.")
    except Exception as e:
        print(f"[PLUGIN] Failed to sync commands: {e}")

def patched_dispatch(self, event_name, *args, **kwargs):
    # 1. Setup Slash Commands on Ready
    if event_name == 'ready' and not COMMANDS_SYNCED:
        asyncio.run_coroutine_threadsafe(setup_real_slash_commands(self), self.loop)

    # 2. Handle Slash Command Interactions
    if event_name == 'interaction':
        interaction = args[0]
        if hasattr(self, 'tree'):
            # Manually trigger the tree to handle the interaction
            self.loop.create_task(self.tree.on_interaction(interaction))
            # DO NOT return here, let original dispatch potentially handle other things if needed

    # 3. Handle Message Filtering (The "Ignore" System)
    if event_name == 'message':
        try:
            message = args[0]
            if not message.author.bot and os.path.exists(IGNORE_FILE):
                with open(IGNORE_FILE, 'r') as f: data = json.load(f)
                if str(message.author.id) in [str(i) for i in data.get('ignored_users', [])] or \
                   str(message.channel.id) in [str(i) for i in data.get('ignored_channels', [])]:
                    return # Block from main.py
        except: pass

    # 4. Standard Dispatch
    return original_dispatch(self, event_name, *args, **kwargs)

discord.Client.dispatch = patched_dispatch

from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import start_http_server

STATS_FILE = 'stats_cache.json'

class StatsHandler(BaseHTTPRequestHandler):
    def __init__(self, metrics, *args, **kwargs):
        self.metrics = metrics
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == '/stats.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            allowed_origins = ['https://yerette.xyz', 'https://purelink-status.pages.dev']
            origin = self.headers.get('Origin')
            if origin in allowed_origins:
                self.send_header('Access-Control-Allow-Origin', origin)
            elif not origin:
                self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            def get_val(m):
                try: return list(m.collect())[0].samples[0].value
                except: return 0.0

            stats = {
                "links_cleaned": get_val(self.metrics['LINKS_CLEANED']),
                "links_detected": get_val(self.metrics['LINKS_DETECTED']),
                "links_nuked": get_val(self.metrics['LINKS_NUKED']),
                "hops_total": get_val(self.metrics['HOPS_TOTAL']),
                "errors_total": get_val(self.metrics['ERRORS_TOTAL']),
                "uptime": time.time() - self.metrics['START_TIME']
            }
            self.wfile.write(json.dumps(stats).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args): return

def persistence_loop(metrics):
    """Background thread to save stats periodically"""
    while True:
        try:
            def get_val(m):
                try: return list(m.collect())[0].samples[0].value
                except: return 0.0
            
            stats = {
                "links_cleaned": get_val(metrics['LINKS_CLEANED']),
                "links_detected": get_val(metrics['LINKS_DETECTED']),
                "links_nuked": get_val(metrics['LINKS_NUKED']),
                "hops_total": get_val(metrics['HOPS_TOTAL']),
                "errors_total": get_val(metrics['ERRORS_TOTAL']),
            }
            with open(STATS_FILE, 'w') as f:
                json.dump(stats, f)
        except: pass
        time.sleep(30)

def initialize_monitoring(metrics):
    # 1. Restore from cache if exists
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
            if 'links_cleaned' in data: metrics['LINKS_CLEANED'].inc(data['links_cleaned'])
            if 'links_detected' in data: metrics['LINKS_DETECTED'].inc(data['links_detected'])
            if 'links_nuked' in data: metrics['LINKS_NUKED'].inc(data['links_nuked'])
            if 'hops_total' in data: metrics['HOPS_TOTAL'].inc(data['hops_total'])
            if 'errors_total' in data: metrics['ERRORS_TOTAL'].inc(data['errors_total'])
        except: pass

    # 2. Start Prometheus (Port 8000)
    try: start_http_server(metrics['PORT_PROM'])
    except: pass

    # 3. Start Persistence Thread
    threading.Thread(target=persistence_loop, args=(metrics,), daemon=True).start()

    # 4. Start JSON API (Port 8001)
    port = int(os.getenv('API_PORT', 8001))
    server = HTTPServer(('0.0.0.0', port), lambda *args, **kwargs: StatsHandler(metrics, *args, **kwargs))
    server.serve_forever()

