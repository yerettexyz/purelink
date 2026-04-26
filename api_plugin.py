import threading
import asyncio
import discord
import os
import json
import time

import slash_commands
from discord import app_commands

# --- Non-Invasive Guard & Slash Commands ---
IGNORE_FILE = 'ignore.json'
original_dispatch = discord.Client.dispatch
COMMANDS_SYNCED = False

# Universal Interaction Hook: This is the missing piece for Client-based slash commands
async def universal_on_interaction(interaction):
    if hasattr(interaction.client, 'tree'):
        await interaction.client.tree.on_interaction(interaction)

discord.Client.on_interaction = universal_on_interaction

async def setup_plugin_system(bot):
    global COMMANDS_SYNCED
    # 4. Command Syncing (Smarter Sync to avoid 429)
    if not hasattr(bot, '_commands_synced'):
        bot._commands_synced = False

    if not bot._commands_synced:
        try:
            if not hasattr(bot, 'tree'):
                bot.tree = app_commands.CommandTree(bot)
            
            # Load commands from external file
            slash_commands.register_commands(bot.tree)

            await bot.tree.sync()
            bot._commands_synced = True
            COMMANDS_SYNCED = True
            print("[PLUGIN] Native Slash Commands synced successfully.")
        except Exception as e:
            print(f"[PLUGIN] Failed to sync commands: {e}")

def patched_dispatch(self, event_name, *args, **kwargs):
    # 1. Setup Slash Commands on Ready
    if event_name == 'ready' and not COMMANDS_SYNCED:
        asyncio.run_coroutine_threadsafe(setup_plugin_system(self), self.loop)

    # 2. Handle Message Filtering (The "Ignore" System)
    if event_name == 'message':
        try:
            message = args[0]
            if not message.author.bot:
                print(f"[DEBUG] Dispatch saw message from {message.author.id} in {message.channel.id}", flush=True)
                if os.path.exists(IGNORE_FILE):
                    with open(IGNORE_FILE, 'r') as f: data = json.load(f)
                    id_list = [str(i) for i in data.get('ignored_users', []) + data.get('ignored_channels', [])]
                    if str(message.author.id) in id_list or str(message.channel.id) in id_list:
                        print(f"[DEBUG] Message BLOCKED by ignore list.", flush=True)
                        return # Block from main.py
        except Exception as e:
            print(f"[DEBUG] Dispatch error: {e}", flush=True)

    # 3. Standard Dispatch
    return original_dispatch(self, event_name, *args, **kwargs)

discord.Client.dispatch = patched_dispatch

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

