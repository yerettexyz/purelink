import discord
from discord import app_commands
import json
import os

IGNORE_FILE = 'ignore.json'

def register_commands(tree):
    @tree.command(name="purelink", description="Show Purelink information")
    async def purelink_info(interaction: discord.Interaction):
        embed = discord.Embed(
            title="Purelink 🛡️",
            description="Purelink is a high-performance URL sanitization bot that restores privacy by stripping affiliate tracking and redirect wrappers.",
            color=0x3498db # Simple Blue
        )
        embed.add_field(name="Source Code", value="[GitHub Repository](https://github.com/yerettexyz/purelink)", inline=False)
        embed.add_field(name="Network Status", value="[Live Status Page](https://purelink-status.pages.dev)", inline=False)
        embed.set_footer(text="Purelink v1.1.0")
        
        logo_path = "IMG_9915.webp"
        if os.path.exists(logo_path):
            file = discord.File(logo_path, filename="logo.webp")
            embed.set_thumbnail(url="attachment://logo.webp")
            await interaction.response.send_message(file=file, embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @tree.command(name="ignore_channel", description="Add a channel to the ignore list")
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

    @tree.command(name="ignore_user", description="Add a user to the ignore list")
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
