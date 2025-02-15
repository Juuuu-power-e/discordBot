import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
from discord.ui import Button, View
import asyncio

# Bot 설정
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='/', intents=intents)

# 필요한 권한 정의
REQUIRED_PERMISSIONS = discord.Permissions(
    manage_channels=True,
    send_messages=True,
    embed_links=True,
    connect=True,
    speak=True,
    use_voice_activation=True,
    manage_messages=True
)

# YT-DLP 옵션
yt_dlp.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'force-ipv4': True,
    'extract_flat': True,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicPlayer:
    def __init__(self, bot, guild, channel):
        self.bot = bot
        self.guild = guild
        self.channel = channel
        self.queue = []
        self.current = None
        self.voice_client = None
        self.is_playing = False

    async def play_next(self):
        if len(self.queue) > 0 and self.voice_client:
            self.is_playing = True
            self.current = self.queue.pop(0)

            self.voice_client.play(self.current, after=lambda e: asyncio.run_coroutine_threadsafe(self._song_finished(),
                                                                                                  self.bot.loop))
            await self.channel.send(f'Now playing: {self.current.title}')
        else:
            self.is_playing = False
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.disconnect()
                await self.channel.send("재생목록이 모두 종료되어 채널에서 나갑니다.")

    async def _song_finished(self):
        if self.voice_client:
            await self.play_next()


class MusicControls(View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="재생", style=discord.ButtonStyle.success)
    async def play_button(self, interaction: discord.Interaction, button: Button):
        if self.player.voice_client and self.player.voice_client.is_paused():
            self.player.voice_client.resume()
            await interaction.response.send_message("재생을 재개합니다.", ephemeral=True)
        else:
            await interaction.response.send_message("이미 재생 중이거나 재생할 곡이 없습니다.", ephemeral=True)

    @discord.ui.button(label="일시정지", style=discord.ButtonStyle.secondary)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        if self.player.voice_client and self.player.voice_client.is_playing():
            self.player.voice_client.pause()
            await interaction.response.send_message("일시정지되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중인 음악이 없습니다.", ephemeral=True)

    @discord.ui.button(label="스킵", style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        if self.player.voice_client and self.player.voice_client.is_playing():
            self.player.voice_client.stop()
            await interaction.response.send_message("다음 곡으로 넘어갑니다.", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중인 음악이 없습니다.", ephemeral=True)


players = {}


@bot.event
async def on_ready():
    print(f'Bot is ready: {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.command(name="setup", description="음악 봇을 위한 전용 채널을 생성합니다.")
async def setup(interaction: discord.Interaction):
    try:
        # 이미 존재하는 음악 채널 확인
        existing_channel = discord.utils.get(interaction.guild.text_channels, name="음악-채널")
        if existing_channel:
            await interaction.response.send_message("음악 채널이 이미 존재합니다!", ephemeral=True)
            return

        # 채널 생성
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(send_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(send_messages=True)
        }

        channel = await interaction.guild.create_text_channel('음악-채널', overwrites=overwrites)

        # 채널 정보 임베드 생성
        embed = discord.Embed(
            title="🎵 음악 봇 컨트롤 패널",
            description="아래 버튼으로 음악을 제어하거나 슬래시 명령어를 사용하세요.",
            color=discord.Color.blue()
        )

        # 명령어 설명 추가
        embed.add_field(
            name="사용 가능한 명령어",
            value="`/play [노래제목 또는 URL]` - 음악 재생\n"
                  "`/pause` - 일시정지\n"
                  "`/resume` - 재생 재개\n"
                  "`/skip` - 다음 곡으로 건너뛰기\n"
                  "`/queue` - 재생 대기열 확인\n"
                  "`/leave` - 음성 채널 나가기",
            inline=False
        )

        # 새로운 플레이어 인스턴스 생성
        players[interaction.guild.id] = MusicPlayer(bot, interaction.guild, channel)
        controls = MusicControls(players[interaction.guild.id])

        await channel.send(embed=embed, view=controls)
        await interaction.response.send_message(
            f"음악 채널이 생성되었습니다! {channel.mention}를 확인해주세요.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "채널을 생성할 권한이 없습니다. 봇의 권한을 확인해주세요.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"채널 생성 중 오류가 발생했습니다: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="play", description="음악을 재생하거나 대기열에 추가합니다.")
async def play(interaction: discord.Interaction, query: str):
    if not interaction.guild.id in players:
        await interaction.response.send_message("먼저 `/setup` 명령어로 음악 채널을 생성해주세요.", ephemeral=True)
        return

    player = players[interaction.guild.id]

    if not interaction.user.voice:
        await interaction.response.send_message("음성 채널에 먼저 입장해주세요.", ephemeral=True)
        return

    if not player.voice_client:
        player.voice_client = await interaction.user.voice.channel.connect()

    await interaction.response.send_message(f"🔍 검색 중: {query}", ephemeral=True)

    try:
        source = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        player.queue.append(source)

        if not player.is_playing:
            await player.play_next()
        else:
            await interaction.followup.send(f"🎵 재생목록에 추가됨: {source.title}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"오류가 발생했습니다: {str(e)}", ephemeral=True)


@bot.tree.command(name="pause", description="현재 재생 중인 음악을 일시정지합니다.")
async def pause(interaction: discord.Interaction):
    if interaction.guild.id in players:
        player = players[interaction.guild.id]
        if player.voice_client and player.voice_client.is_playing():
            player.voice_client.pause()
            await interaction.response.send_message("일시정지되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중인 음악이 없습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("음악 플레이어가 설정되지 않았습니다.", ephemeral=True)


@bot.tree.command(name="resume", description="일시정지된 음악을 다시 재생합니다.")
async def resume(interaction: discord.Interaction):
    if interaction.guild.id in players:
        player = players[interaction.guild.id]
        if player.voice_client and player.voice_client.is_paused():
            player.voice_client.resume()
            await interaction.response.send_message("재생을 재개합니다.", ephemeral=True)
        else:
            await interaction.response.send_message("일시정지된 음악이 없습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("음악 플레이어가 설정되지 않았습니다.", ephemeral=True)


@bot.tree.command(name="skip", description="현재 재생 중인 음악을 건너뜁니다.")
async def skip(interaction: discord.Interaction):
    if interaction.guild.id in players:
        player = players[interaction.guild.id]
        if player.voice_client and player.voice_client.is_playing():
            player.voice_client.stop()
            await interaction.response.send_message("다음 곡으로 넘어갑니다.", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중인 음악이 없습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("음악 플레이어가 설정되지 않았습니다.", ephemeral=True)


@bot.tree.command(name="queue", description="현재 재생 대기열을 보여줍니다.")
async def queue(interaction: discord.Interaction):
    if interaction.guild.id in players:
        player = players[interaction.guild.id]
        if not player.queue and not player.current:
            await interaction.response.send_message("재생 대기열이 비어있습니다.", ephemeral=True)
            return

        embed = discord.Embed(title="🎵 재생 대기열", color=discord.Color.blue())

        if player.current:
            embed.add_field(name="현재 재생 중", value=player.current.title, inline=False)

        if player.queue:
            queue_list = "\n".join([f"{i + 1}. {song.title}" for i, song in enumerate(player.queue)])
            embed.add_field(name="대기열", value=queue_list, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("음악 플레이어가 설정되지 않았습니다.", ephemeral=True)


@bot.tree.command(name="leave", description="음성 채널에서 나갑니다.")
async def leave(interaction: discord.Interaction):
    if interaction.guild.id in players:
        player = players[interaction.guild.id]
        if player.voice_client:
            await player.voice_client.disconnect()
            player.queue.clear()
            player.current = None
            player.is_playing = False
            await interaction.response.send_message("음성 채널에서 나갔습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("음성 채널에 입장해있지 않습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("음악 플레이어가 설정되지 않았습니다.", ephemeral=True)


# Bot 토큰으로 실행
bot.run('YOUR_BOT_TOKEN')