<h1 align="center">Purelink Discord Bot</h1>
<p align="center">
	<b>Advanced link purification for clean, affiliate-free conversations.</b>
</p>

Purelink is a high-performance fork of the ClearURLs Discord Bot, specifically tailored to detect, clean, and unwrap tracking links. It specializes in following affiliate redirects (like Mavely) to extract pure destination URLs before they clutter your chat.

## Key Features
- **Mavely Unwrapping**: Automatically follows redirects (up to 5 hops) for `mavely.app` and `joinmavely.com` links.
- **Webhook Reposting**: Seamlessly deletes original "dirty" messages and reposts them as the original user (using webhooks) with pure links.
- **Privacy Enhanced**: Strips UTM and other tracking parameters using the [Unalix](https://github.com/AmanoTeam/Unalix) library.
- **Minimal Footprint**: Adds a subtle "Link cleaned by Purelink" footer to processed messages.

---

## 🛠 Self-Hosting Setup

### 1. Requirements
- Python 3.8+
- Discord Bot Token with **Message Content Intent** enabled.

### 2. Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/psalm2517/purelink.git
   cd purelink
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Prepare configuration:
   - Rename `.env.example` to `.env`.
   - Open `.env` and paste your Discord bot token in the `TOKEN=` field.

### 3. Oracle Cloud Deployment (Ubuntu)
To run Purelink 24/7 on an Oracle Cloud VPS:

1. **Setup Environment**:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure Service**:
   ```bash
   sudo cp purelink.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable purelink
   sudo systemctl start purelink
   ```
3. **Monitor Logs**:
   ```bash
   sudo journalctl -u purelink -f
   ```

### 4. Permissions
The bot requires the following permissions in your Discord server:
- **Manage Messages**: To delete original tracking link messages.
- **Manage Webhooks**: To repost cleaned messages as the original user.
- **Send Messages**: General function.
- **Read Message History**: To process incoming links.

### 5. Running the Bot Locally
```bash
python main.py
```

---

## License & Attribution
Purelink is licensed under **LGPL-3.0**. 
- Based on the original work by [DanielZTing](https://github.com/DanielZTing/clearurls-discord-bot).
- Portions of the logic use [Unalix](https://github.com/AmanoTeam/Unalix).
