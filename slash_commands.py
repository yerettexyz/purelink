import discord
from discord import app_commands
import json
import os

IGNORE_FILE = 'ignore.json'

def register_commands(tree):
    @tree.command(name="purelink_help", description="Show Purelink plugin help")
    async def help_cmd(interaction: discord.Interaction):
        help_text = (
            "💡 **Purelink Plugin Help**\n"
            "`/ignore_channel <id>` - Stop bot from cleaning links in a channel\n"
            "`/ignore_user <id>` - Stop bot from cleaning links for a user\n"
            "-# *Native Slash Commands System*"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

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
