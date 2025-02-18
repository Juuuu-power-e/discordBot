import discord
from discord.ui import View, Button

class MusicControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="대기열", style=discord.ButtonStyle.primary, emoji="📋")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_queue(interaction)
