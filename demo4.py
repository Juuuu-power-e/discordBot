import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import yt_dlp
import asyncio
from async_timeout import timeout
from functools import partial
import itertools



load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")


# YT-DLP 옵션
ytdlp_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,  # 재생목록 허용
    'nocheckcertificate': True,
    'ignoreerrors': True,  # 오류 무시 옵션 활성화
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'force-ipv4': True,
    'extract_flat': True,  # 플레이리스트 초기 추출을 평면화
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
    def __init__(self, bot):
        self.bot = bot
        self.queue = {}
        self.current = {}
        self.loop = asyncio.get_event_loop()  # 이벤트 루프 초기화

    async def cog_load(self):
        """Cog가 로드될 때 호출되는 메서드"""
        pass

    @commands.command(name='join')
    async def join(self, ctx):
        """음성 채널에 입장"""
        if ctx.author.voice is None:
            await ctx.send("음성 채널에 먼저 입장해주세요!")
            return

        channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx, *, url):
        """YouTube URL 또는 검색어로 음악 재생"""
        async with ctx.typing():
            try:
                if ctx.voice_client is None:
                    await ctx.invoke(self.join)

                if ctx.guild.id not in self.queue:
                    self.queue[ctx.guild.id] = []

                if not any(s in url for s in ['youtube.com', 'youtu.be']):
                    url = f"ytsearch:{url}"

                sources = await YTDLPSource.from_url(url, loop=self.loop, stream=True)

                self.queue[ctx.guild.id].extend(sources)

                if len(sources) > 1:
                    await ctx.send(f'재생목록에 {len(sources)}개의 곡이 추가되었습니다.')
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
                    await ctx.send(embed=embed)

                if not ctx.voice_client.is_playing():
                    await self.play_next(ctx)

            except Exception as e:
                await ctx.send(f'오류가 발생했습니다: {str(e)}')

    async def play_next(self, ctx):
        """다음 곡 재생"""
        if not self.queue[ctx.guild.id]:
            await ctx.send("재생할 곡이 없습니다.")
            return

        # 대기열에서 다음 곡 가져오기
        source = self.queue[ctx.guild.id].pop(0)
        self.current[ctx.guild.id] = source

        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
            self.play_next(ctx), self.loop).result() if e is None else print(f'Player error: {e}'))

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
        await ctx.send(embed=embed)

    @commands.command(name='pause')
    async def pause(self, ctx):
        """재생 일시정지"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("일시정지되었습니다.")
        else:
            await ctx.send("현재 재생 중인 곡이 없습니다.")

    @commands.command(name='resume')
    async def resume(self, ctx):
        """재생 재개"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("재생이 재개되었습니다.")
        else:
            await ctx.send("일시정지된 곡이 없습니다.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        """현재 곡 건너뛰기"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("다음 곡으로 넘어갑니다.")
        else:
            await ctx.send("현재 재생 중인 곡이 없습니다.")

    @commands.command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """재생 대기열 확인"""
        if ctx.guild.id not in self.queue or not self.queue[ctx.guild.id]:
            await ctx.send("재생 대기열이 비어있습니다.")
            return

        upcoming = list(itertools.islice(self.queue[ctx.guild.id], 0, 5))

        embed = discord.Embed(
            title="재생 대기열",
            description=f"다음 {len(self.queue[ctx.guild.id])}개의 곡이 대기 중입니다.",
            color=discord.Color.blue()
        )

        for i, song in enumerate(upcoming, 1):
            embed.add_field(
                name=f"{i}. {song.title}",
                value=f"길이: {int(song.duration // 60)}:{int(song.duration % 60):02d}" if song.duration else "길이 정보 없음",
                inline=False
            )

        if len(self.queue[ctx.guild.id]) > 5:
            embed.set_footer(text=f"외 {len(self.queue[ctx.guild.id]) - 5}개의 곡")

        await ctx.send(embed=embed)

    @commands.command(name='clear')
    async def clear(self, ctx):
        """재생 대기열 초기화"""
        if ctx.guild.id in self.queue:
            self.queue[ctx.guild.id] = []
            await ctx.send("재생 대기열이 초기화되었습니다.")
        else:
            await ctx.send("재생 대기열이 이미 비어있습니다.")

    @commands.command(name='stop')
    async def stop(self, ctx):
        """재생 중지 및 대기열 초기화"""
        if ctx.guild.id in self.queue:
            self.queue[ctx.guild.id] = []
        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect()
            await ctx.send("재생을 중지하고 대기열을 초기화했습니다.")
        else:
            await ctx.send("이미 음성 채널에서 나와있습니다.")

    @commands.command(name='np', aliases=['now'])
    async def now_playing(self, ctx):
        """현재 재생 중인 곡 정보"""
        if ctx.guild.id not in self.current or not ctx.voice_client.is_playing():
            await ctx.send("현재 재생 중인 곡이 없습니다.")
            return

        source = self.current[ctx.guild.id]
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
        await ctx.send(embed=embed)


async def setup(bot):
    """비동기 설정 함수"""
    await bot.add_cog(MusicBot(bot))


async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.guild_messages = True



    bot = commands.Bot(command_prefix='!', intents=intents)

    @bot.event
    async def on_ready():
        print(f'Bot is ready! Logged in as {bot.user}')
        await bot.change_presence(activity=discord.Game(name="!help"))


    await setup(bot)  # Cog 비동기 설정
    await bot.start(TOKEN)

# 봇 실행
if __name__ == "__main__":
    asyncio.run(main())