from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
import asyncio

from config.bot_config import BotConfig
from services.music_manager import MusicManager
from ui.views import MusicControlView
from ui.embeds import MusicEmbeds
from utils.exceptions import VoiceConnectionError


class MusicBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = BotConfig.load_config()
        self.music_manager = MusicManager(self.config)
        self.loop = asyncio.get_event_loop()

    async def cog_load(self):
        print("MusicBot cog loaded!")
        await self.initialize_music_channels()

    async def initialize_music_channels(self):
        """초기 음악 채널 설정 및 컨트롤 패널 초기화"""
        for guild in self.bot.guilds:
            try:
                music_channel = discord.utils.get(
                    guild.text_channels,
                    name=self.config.MUSIC_CHANNEL_NAME
                )
                if music_channel:
                    print(f"Found existing music channel in {guild.name}")
                    await self.setup_control_panel(music_channel)
            except Exception as e:
                print(f"Error initializing music channel in {guild.name}: {e}")

    async def setup_control_panel(self, channel: discord.TextChannel):
        """음악 컨트롤 패널 설정"""
        try:
            # 기존 메시지 삭제
            await channel.purge()
            # 새 컨트롤 패널 생성
            embed = await MusicEmbeds.create_control_panel_embed()
            view = MusicControlView(self.bot)
            await channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"Error setting up control panel: {e}")

    @app_commands.command(name='play', description='YouTube URL 또는 검색어로 음악을 재생합니다')
    @app_commands.describe(query='재생할 노래의 제목이나 URL을 입력하세요')
    async def play(self, interaction: discord.Interaction, query: str):
        """음악 재생 명령어"""
        await self.play_music(interaction, query)

    @app_commands.command(name='p', description='play 명령어의 단축어입니다')
    async def play_alias_p(self, interaction: discord.Interaction, query: str):
        await self.play_music(interaction, query)

    async def play_music(self, interaction: discord.Interaction, query: str):
        """음악 재생 로직 처리"""
        await interaction.response.defer()

        try:
            # 음성 채널 연결 확인
            if not await self.ensure_voice_connected(interaction):
                return

            # 대기열 초기화
            guild_id = interaction.guild_id
            if guild_id not in self.music_manager.queue:
                self.music_manager.queue[guild_id] = []

            # 음악 추가 및 재생
            sources = await self.music_manager.process_query(query, self.loop)
            if not sources:
                await interaction.followup.send("음악을 찾을 수 없습니다.")
                return

            # 대기열에 추가
            self.music_manager.queue[guild_id].extend(sources)

            # 현재 재생 중이 아니면 재생 시작
            if not interaction.guild.voice_client.is_playing():
                await self.play_next(interaction)

            # 대기열 추가 메시지 전송
            await self.send_queue_update(interaction, len(sources))

        except VoiceConnectionError as e:
            await interaction.followup.send(str(e))
        except Exception as e:
            print(f"Error in play_music: {e}")
            await interaction.followup.send("음악 재생 중 오류가 발생했습니다.")

    async def ensure_voice_connected(self, interaction: discord.Interaction) -> bool:
        """음성 채널 연결 상태 확인 및 연결"""
        if not interaction.guild.voice_client:
            if interaction.user.voice:
                try:
                    await interaction.user.voice.channel.connect()
                    return True
                except Exception as e:
                    raise VoiceConnectionError(f"음성 채널 연결 실패: {str(e)}")
            else:
                raise VoiceConnectionError("음성 채널에 먼저 입장해주세요!")
        return True

    async def play_next(self, interaction: discord.Interaction):
        """다음 곡 재생"""
        guild_id = interaction.guild_id
        if not self.music_manager.queue[guild_id]:
            await self.handle_empty_queue(interaction)
            return

        try:
            # 다음 곡 가져오기
            source = self.music_manager.queue[guild_id].pop(0)
            self.music_manager.current[guild_id] = source

            # 재생 시작
            interaction.guild.voice_client.play(
                source,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.handle_playback_error(interaction, e),
                    self.loop
                )
            )

            # 재생 중 메시지 전송
            embed = await MusicEmbeds.create_now_playing_embed(source)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Error in play_next: {e}")
            await interaction.followup.send("다음 곡 재생 중 오류가 발생했습니다.")

    async def handle_empty_queue(self, interaction: discord.Interaction):
        """빈 대기열 처리"""
        await interaction.followup.send(
            "재생할 곡이 없습니다. 3분 내에 음악이 추가되지 않으면 자동으로 연결이 종료됩니다."
        )

        try:
            await asyncio.sleep(180)  # 3분 대기
            if (not self.music_manager.queue[interaction.guild_id] and
                    interaction.guild.voice_client and
                    not interaction.guild.voice_client.is_playing()):
                await interaction.guild.voice_client.disconnect()
                await interaction.followup.send("3분 동안 아무 곡도 추가되지 않아 연결을 종료합니다.")
        except Exception as e:
            print(f"Error in handle_empty_queue: {e}")

    async def handle_playback_error(self, interaction: discord.Interaction, error):
        """재생 중 에러 처리"""
        if error:
            print(f"Playback error: {error}")
            await interaction.followup.send("재생 중 오류가 발생했습니다.")
        else:
            await self.play_next(interaction)

    @app_commands.command(name='skip', description='현재 재생 중인 곡을 건너뜁니다')
    async def skip(self, interaction: discord.Interaction):
        """현재 곡 건너뛰기"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("다음 곡으로 넘어갑니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='queue', description='재생 대기열을 확인합니다')
    async def queue(self, interaction: discord.Interaction):
        """대기열 표시"""
        guild_id = interaction.guild_id
        if guild_id not in self.music_manager.queue or not self.music_manager.queue[guild_id]:
            await interaction.response.send_message("재생 대기열이 비어있습니다.", ephemeral=True)
            return

        try:
            embed = await MusicEmbeds.create_queue_embed(
                self.music_manager.queue[guild_id],
                self.music_manager.current.get(guild_id)
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            print(f"Error showing queue: {e}")
            await interaction.response.send_message("대기열을 표시하는 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name='pause', description='현재 재생 중인 음악을 일시정지합니다')
    async def pause(self, interaction: discord.Interaction):
        """음악 일시정지"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("일시정지되었습니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='resume', description='일시정지된 음악을 다시 재생합니다')
    async def resume(self, interaction: discord.Interaction):
        """음악 재생 재개"""
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("재생이 재개되었습니다.")
        else:
            await interaction.response.send_message("일시정지된 곡이 없습니다.", ephemeral=True)

    @app_commands.command(name='stop', description='재생을 중지하고 대기열을 초기화합니다')
    async def stop(self, interaction: discord.Interaction):
        """재생 중지 및 대기열 초기화"""
        guild_id = interaction.guild_id
        if guild_id in self.music_manager.queue:
            self.music_manager.queue[guild_id].clear()
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("재생을 중지하고 대기열을 초기화했습니다.")
        else:
            await interaction.response.send_message("이미 음성 채널에서 나와있습니다.", ephemeral=True)

    @app_commands.command(name='help', description='봇의 명령어 목록과 사용법을 보여줍니다')
    async def help(self, interaction: discord.Interaction):
        """도움말 표시"""
        embed = await MusicEmbeds.create_help_embed()
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicBot(bot))