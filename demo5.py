import os
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
from async_timeout import timeout
from functools import partial
import itertools

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# YT-DLP 옵션은 동일하게 유지
ytdlp_format_options = {
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
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdlp = yt_dlp.YoutubeDL(ytdlp_format_options)


class YTDLPSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()

        try:
            # 먼저 플레이리스트 정보를 가져옴
            playlist_data = await loop.run_in_executor(None, lambda: ytdlp.extract_info(url, download=not stream))
        except Exception as e:
            print(f"Error extracting playlist info: {e}")
            return []

        playlist = []

        if 'entries' in playlist_data:
            # 재생목록인 경우
            successful_entries = 0
            failed_entries = 0

            for entry in playlist_data['entries']:
                if entry:
                    try:
                        # 각 동영상의 상세 정보를 가져옴
                        webpage_url = entry.get('url') or entry.get('webpage_url')
                        if not webpage_url:
                            continue

                        # 동영상별 옵션 설정 (플랫 추출 비활성화)
                        video_options = ytdlp_format_options.copy()
                        video_options['extract_flat'] = False

                        with yt_dlp.YoutubeDL(video_options) as ydl:
                            entry_data = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url,
                                                                                                   download=not stream))

                        if entry_data:
                            source = cls(discord.FFmpegPCMAudio(
                                entry_data['url'],
                                **ffmpeg_options
                            ), data=entry_data)
                            playlist.append(source)
                            successful_entries += 1

                    except Exception as e:
                        print(f"Error processing playlist entry: {e}")
                        failed_entries += 1
                        continue

            print(f"Successfully added {successful_entries} tracks, {failed_entries} failed")
            return playlist
        else:
            # 단일 영상인 경우
            try:
                data = await loop.run_in_executor(None, lambda: ytdlp.extract_info(url, download=not stream))
                return [cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data)]
            except Exception as e:
                print(f"Error processing single video: {e}")
                return []


class MusicBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = {}
        self.current = {}
        self.loop = asyncio.get_event_loop()

    async def cog_load(self):
        print("MusicBot cog loaded!")

    @app_commands.command(name='join', description='음성 채널에 봇을 입장시킵니다')
    async def join(self, interaction: discord.Interaction):
        if interaction.user.voice is None:
            await interaction.response.send_message("음성 채널에 먼저 입장해주세요!", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect()

        await interaction.response.send_message(f"{channel.name} 채널에 입장했습니다!")

    @app_commands.command(name='play', description='YouTube URL 또는 검색어로 음악을 재생합니다')
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        try:
            if interaction.guild.voice_client is None:
                if interaction.user.voice:
                    await interaction.user.voice.channel.connect()
                else:
                    await interaction.followup.send("음성 채널에 먼저 입장해주세요!")
                    return

            if interaction.guild.id not in self.queue:
                self.queue[interaction.guild.id] = []

            if not any(s in query for s in ['youtube.com', 'youtu.be']):
                query = f"ytsearch:{query}"

            sources = await YTDLPSource.from_url(query, loop=self.loop, stream=True)
            self.queue[interaction.guild.id].extend(sources)

            if len(sources) > 1:
                await interaction.followup.send(f'재생목록에 {len(sources)}개의 곡이 추가되었습니다.')
            else:
                embed = discord.Embed(
                    title="대기열에 추가됨",
                    description=f"[{sources[0].title}]({sources[0].webpage_url})",
                    color=discord.Color.green()
                )
                if sources[0].thumbnail:
                    embed.set_thumbnail(url=sources[0].thumbnail)
                if sources[0].duration:
                    embed.add_field(
                        name="길이",
                        value=f"{int(sources[0].duration // 60)}:{int(sources[0].duration % 60):02d}"
                    )
                await interaction.followup.send(embed=embed)

            if not interaction.guild.voice_client.is_playing():
                await self.play_next(interaction)

        except Exception as e:
            await interaction.followup.send(f'오류가 발생했습니다: {str(e)}')

    @app_commands.command(name='pause', description='현재 재생 중인 음악을 일시정지합니다')
    async def pause(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("일시정지되었습니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='resume', description='일시정지된 음악을 다시 재생합니다')
    async def resume(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("재생이 재개되었습니다.")
        else:
            await interaction.response.send_message("일시정지된 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='skip', description='현재 재생 중인 곡을 건너뜁니다')
    async def skip(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("다음 곡으로 넘어갑니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='queue', description='재생 대기열을 확인합니다')
    async def queue_info(self, interaction: discord.Interaction):
        if interaction.guild.id not in self.queue or not self.queue[interaction.guild.id]:
            await interaction.response.send_message("재생 대기열이 비어있습니다.", ephemeral=True)
            return

        upcoming = list(itertools.islice(self.queue[interaction.guild.id], 0, 5))
        embed = discord.Embed(
            title="재생 대기열",
            description=f"다음 {len(self.queue[interaction.guild.id])}개의 곡이 대기 중입니다.",
            color=discord.Color.blue()
        )

        for i, song in enumerate(upcoming, 1):
            embed.add_field(
                name=f"{i}. {song.title}",
                value=f"길이: {int(song.duration // 60)}:{int(song.duration % 60):02d}" if song.duration else "길이 정보 없음",
                inline=False
            )

        if len(self.queue[interaction.guild.id]) > 5:
            embed.set_footer(text=f"외 {len(self.queue[interaction.guild.id]) - 5}개의 곡")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='clear', description='재생 대기열을 초기화합니다')
    async def clear(self, interaction: discord.Interaction):
        if interaction.guild.id in self.queue:
            self.queue[interaction.guild.id] = []
            await interaction.response.send_message("재생 대기열이 초기화되었습니다.")
        else:
            await interaction.response.send_message("재생 대기열이 이미 비어있습니다.", ephemeral=True)

    @app_commands.command(name='stop', description='재생을 중지하고 음성 채널에서 나갑니다')
    async def stop(self, interaction: discord.Interaction):
        if interaction.guild.id in self.queue:
            self.queue[interaction.guild.id] = []
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("재생을 중지하고 대기열을 초기화했습니다.")
        else:
            await interaction.response.send_message("이미 음성 채널에서 나와있습니다.", ephemeral=True)

    @app_commands.command(name='np', description='현재 재생 중인 곡의 정보를 표시합니다')
    async def now_playing(self, interaction: discord.Interaction):
        if interaction.guild.id not in self.current or not interaction.guild.voice_client.is_playing():
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)
            return

        source = self.current[interaction.guild.id]
        embed = discord.Embed(
            title="현재 재생 중",
            description=f"[{source.title}]({source.webpage_url})",
            color=discord.Color.blue()
        )
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        if source.duration:
            embed.add_field(
                name="길이",
                value=f"{int(source.duration // 60)}:{int(source.duration % 60):02d}"
            )
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name='disconnect', description='봇을 음성 채널에서 내보냅니다')
    async def disconnect(self, interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            if interaction.guild.id in self.queue:
                self.queue[interaction.guild.id].clear()
            if interaction.guild.id in self.current:
                del self.current[interaction.guild.id]
            await interaction.response.send_message("음성 채널에서 나갔습니다.")
        else:
            await interaction.response.send_message("이미 음성 채널에서 나와있습니다.", ephemeral=True)


    async def play_next(self, interaction: discord.Interaction):
        if not self.queue[interaction.guild.id]:
            await interaction.followup.send("재생할 곡이 없습니다. 3분 내에 음악이 추가되지 않으면 자동으로 연결이 종료됩니다.")

            try:
                # 3분 대기
                await asyncio.sleep(180)

                # 3분 후에도 대기열이 비어있고 재생 중이 아니면 연결 종료
                if (not self.queue[interaction.guild.id] and
                        interaction.guild.voice_client and
                        not interaction.guild.voice_client.is_playing()):
                    await interaction.guild.voice_client.disconnect()
                    await interaction.followup.send("3분 동안 아무 곡도 추가되지 않아 연결을 종료합니다.")
            except Exception as e:
                print(f"자동 연결 종료 중 오류 발생: {e}")
            return

        source = self.queue[interaction.guild.id].pop(0)
        self.current[interaction.guild.id] = source

        interaction.guild.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
            self.play_next(interaction), self.loop).result() if e is None else print(f'Player error: {e}'))

        embed = discord.Embed(
            title="현재 재생 중",
            description=f"[{source.title}]({source.webpage_url})",
            color=discord.Color.blue()
        )
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        if source.duration:
            embed.add_field(
                name="길이",
                value=f"{int(source.duration // 60)}:{int(source.duration % 60):02d}"
            )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicBot(bot))
    print("MusicBot setup complete!")


async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.guild_messages = True

    class MusicBotClient(commands.Bot):
        def __init__(self):
            super().__init__(command_prefix='!', intents=intents)

        async def setup_hook(self):
            await setup(self)
            await self.tree.sync()  # 슬래시 커맨드 동기화

    bot = MusicBotClient()

    @bot.event
    async def on_ready():
        print(f'Bot is ready! Logged in as {bot.user}')
        await bot.change_presence(activity=discord.Game(name="/help"))

    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())