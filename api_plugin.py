import threading
import discord
import os
import json
import time

# --- Non-Invasive Guard (Monkey Patch) ---
# This intercepts messages before they reach main.py without touching main.py
IGNORE_FILE = 'ignore.json'
original_dispatch = discord.Client.dispatch

def patched_dispatch(self, event_name, *args, **kwargs):
    if event_name == 'message':
        try:
            message = args[0]
            if os.path.exists(IGNORE_FILE):
                with open(IGNORE_FILE, 'r') as f:
                    data = json.load(f)
                if message.author.id in data.get('ignored_users', []) or \
                   message.channel.id in data.get('ignored_channels', []):
                    return # Drop the message before main.py sees it
        except: pass
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

