import discord
from typing import Optional

class YTDLPSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)
        self.data: dict = data
        self.title: str = data.get('title', 'No title')
        self.url: str = data.get('url', '')
        self.duration: Optional[int] = data.get('duration')
        self.thumbnail: Optional[str] = data.get('thumbnail')
        self.webpage_url: Optional[str] = data.get('webpage_url')