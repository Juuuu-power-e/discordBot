from dataclasses import dataclass
from typing import Dict, Any
from dotenv import load_dotenv


@dataclass
class BotConfig:
    MUSIC_CHANNEL_NAME: str
    YTDLP_FORMAT_OPTIONS: Dict[str, Any]
    FFMPEG_OPTIONS: Dict[str, Any]

    @classmethod
    def load_config(cls) -> 'BotConfig':
        load_dotenv()
        return cls(
            MUSIC_CHANNEL_NAME='우타의 노래방♪',
            YTDLP_FORMAT_OPTIONS={
                'format': 'bestaudio/best',
                'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
                'restrictfilenames': True,
                'noplaylist': False,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'logtostderr': False,
                'quiet': True,
                'no_warnings': True,
                'default_search': 'auto',
                'source_address': '0.0.0.0',
                'force-ipv4': True,
                'extract_flat': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            },
            FFMPEG_OPTIONS={
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
        )
