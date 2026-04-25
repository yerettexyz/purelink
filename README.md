<h1 align="center">Purelink Discord Bot</h1>
<p align="center">
	<b>Link purification for Discord.</b>
</p>

Purelink is a bot designed to detect, unwrap, and clean tracking links, extracting destination URLs from affiliate redirect chains.

## 🚀 Quick Start

**[Add Purelink to Discord](https://yerette.xyz/purelink)**

## Key Features
- **3,500+ Tracking Domains**: Integrated blocklist for unwrapping and sanitizing ad, affiliate, and tracking domains.
- **Mavely & Amazon Sanitization**: Logic for cleaning Mavely redirects and stripping Amazon tracking parameters.
- **Webhook Reposting**: Deletes messages containing tracking links and reposts them using the original user's name and avatar with cleaned URLs.
- **Dynamic Configuration**: Decoupled `data.json` for managing tracking rules.
- **Security Hardened**: IP-level SSRF protection, strict TLS verification, and 5-link processing cap per message.
- **Multi-Hop Chain Resolution**: Resolution logic for tracing deeply nested affiliate redirect chains.

---

## 🛠 Self-Hosting Setup

### 1. Requirements
- Python 3.8+
- Discord Bot Token with **Message Content Intent** enabled.

### 2. Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/yerettexyz/purelink.git
   cd purelink
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Prepare configuration:
   - Rename `.env.example` to `.env`.
   - Add your Discord bot token to the `TOKEN=` field in `.env`.

### 3. Oracle Cloud Deployment (Ubuntu)
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
Required bot permissions:
- **Manage Messages**: To delete original tracking link messages.
- **Manage Webhooks**: To repost cleaned messages.
- **Send Messages**: General function.
- **Read Message History**: To process incoming links.

### 5. Execution
```bash
python main.py
```

## 🤝 Contributing
To report an uncleaned link: [Open a Domain Suggestion issue](https://github.com/psalm2517/purelink/issues/new?template=domain_request.md).

---

## License & Attribution
Purelink is licensed under **LGPL-3.0**. 
- Based on code by [DanielZTing](https://github.com/DanielZTing/clearurls-discord-bot).
- Logic adapted from [Unalix](https://github.com/AmanoTeam/Unalix).
