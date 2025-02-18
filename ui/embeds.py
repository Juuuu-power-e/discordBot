import discord
from datetime import datetime

class MusicEmbeds:
    @staticmethod
    def create_now_playing_embed(source: 'YTDLPSource') -> discord.Embed:
        embed = discord.Embed(
            title="현재 재생 중",
            description=f"[{source.title}]({source.webpage_url})",
            color=discord.Color.blue()
        )
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        return embed