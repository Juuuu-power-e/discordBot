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
import psutil
import json
import re
from datetime import datetime


load_dotenv()
token = os.getenv("DISCORD_BOT_TOKEN")
discord_tag = os.getenv("DISCORD_TAG")
github_profile = os.getenv("GITHUB_PROFILE")


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

    # @classmethod
    # async def from_url(cls, url, *, loop=None, stream=False):
    #     loop = loop or asyncio.get_event_loop()
    #
    #     try:
    #         # 먼저 플레이리스트 정보를 가져옴
    #         playlist_data = await loop.run_in_executor(None, lambda: ytdlp.extract_info(url, download=not stream))
    #     except Exception as e:
    #         print(f"Error extracting playlist info: {e}")
    #         return []
    #
    #     playlist = []
    #
    #     if 'entries' in playlist_data:
    #         # 재생목록인 경우
    #         successful_entries = 0
    #         failed_entries = 0
    #
    #         for entry in playlist_data['entries']:
    #             if entry:
    #                 try:
    #                     # 각 동영상의 상세 정보를 가져옴
    #                     webpage_url = entry.get('url') or entry.get('webpage_url')
    #                     if not webpage_url:
    #                         continue
    #
    #                     # 동영상별 옵션 설정 (플랫 추출 비활성화)
    #                     video_options = ytdlp_format_options.copy()
    #                     video_options['extract_flat'] = False
    #
    #                     with yt_dlp.YoutubeDL(video_options) as ydl:
    #                         entry_data = await loop.run_in_executor(None, lambda: ydl.extract_info(webpage_url,
    #                                                                                                download=not stream))
    #
    #                     if entry_data:
    #                         source = cls(discord.FFmpegPCMAudio(
    #                             entry_data['url'],
    #                             **ffmpeg_options
    #                         ), data=entry_data)
    #                         playlist.append(source)
    #                         successful_entries += 1
    #
    #                 except Exception as e:
    #                     print(f"Error processing playlist entry: {e}")
    #                     failed_entries += 1
    #                     continue
    #
    #         print(f"Successfully added {successful_entries} tracks, {failed_entries} failed")
    #         return playlist
    #     else:
    #         # 단일 영상인 경우
    #         try:
    #             data = await loop.run_in_executor(None, lambda: ytdlp.extract_info(url, download=not stream))
    #             return [cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data)]
    #         except Exception as e:
    #             print(f"Error processing single video: {e}")
    #             return []


class MusicBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = {}
        self.current = {}
        self.loop = asyncio.get_event_loop()

    # Join 명령어
    @app_commands.command(name='join', description='음성 채널에 봇을 입장시킵니다')
    async def join_command(self, interaction: discord.Interaction):
        await self.join_voice_channel(interaction)

    async def join_voice_channel(self, interaction: discord.Interaction):
        if interaction.user.voice is None:
            await interaction.response.send_message("음성 채널에 먼저 입장해주세요!", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect()

        await interaction.response.send_message(f"{channel.name} 채널에 입장했습니다!")

    # Pause 명령어
    @app_commands.command(name='pause', description='현재 재생 중인 음악을 일시정지합니다')
    async def pause_command(self, interaction: discord.Interaction):
        await self.pause_music(interaction)

    async def pause_music(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            await interaction.response.send_message("일시정지되었습니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    # Resume 명령어
    @app_commands.command(name='resume', description='일시정지된 음악을 다시 재생합니다')
    async def resume_command(self, interaction: discord.Interaction):
        await self.resume_music(interaction)

    async def resume_music(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            await interaction.response.send_message("재생이 재개되었습니다.")
        else:
            await interaction.response.send_message("일시정지된 곡이 없습니다.", ephemeral=True)

    # Skip 명령어
    @app_commands.command(name='skip', description='현재 재생 중인 곡을 건너뜁니다')
    async def skip_command(self, interaction: discord.Interaction):
        await self.skip_music(interaction)

    async def skip_music(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("다음 곡으로 넘어갑니다.")
        else:
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)

    # Queue 명령어
    @app_commands.command(name='queue', description='재생 대기열을 확인합니다')
    async def queue_command(self, interaction: discord.Interaction):
        await self.show_queue(interaction)

    async def show_queue(self, interaction: discord.Interaction):
        print('showing queue')
        if interaction.guild.id not in self.queue or not self.queue[interaction.guild.id]:
            await interaction.response.send_message("재생 대기열이 비어있습니다.", ephemeral=True)
            return

        upcoming = list(itertools.islice(self.queue[interaction.guild.id], 0, 5))
        print(upcoming)
        embed = await self.create_queue_embed(interaction, upcoming)
        print(embed)
        await interaction.response.send_message(embed=embed)
        print("end")

    async def create_queue_embed(self, interaction: discord.Interaction, upcoming):
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

        return embed

    # Clear 명령어
    @app_commands.command(name='clear', description='재생 대기열을 초기화합니다')
    async def clear_command(self, interaction: discord.Interaction):
        await self.clear_queue(interaction)

    async def clear_queue(self, interaction: discord.Interaction):
        if interaction.guild.id in self.queue:
            self.queue[interaction.guild.id] = []
            await interaction.response.send_message("재생 대기열이 초기화되었습니다.")
        else:
            await interaction.response.send_message("재생 대기열이 이미 비어있습니다.", ephemeral=True)

    # Stop 명령어
    @app_commands.command(name='stop', description='재생을 중지하고 음성 채널에서 나갑니다')
    async def stop_command(self, interaction: discord.Interaction):
        await self.stop_music(interaction)

    async def stop_music(self, interaction: discord.Interaction):
        if interaction.guild.id in self.queue:
            self.queue[interaction.guild.id] = []
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("재생을 중지하고 대기열을 초기화했습니다.")
        else:
            await interaction.response.send_message("이미 음성 채널에서 나와있습니다.", ephemeral=True)

    # Now Playing 명령어
    @app_commands.command(name='np', description='현재 재생 중인 곡의 정보를 표시합니다')
    async def now_playing_command(self, interaction: discord.Interaction):
        await self.show_now_playing(interaction)

    async def show_now_playing(self, interaction: discord.Interaction):
        if interaction.guild.id not in self.current or not interaction.guild.voice_client.is_playing():
            await interaction.response.send_message("현재 재생 중인 곡이 없습니다.", ephemeral=True)
            return

        source = self.current[interaction.guild.id]
        embed = await self.create_now_playing_embed(source)
        await interaction.response.send_message(embed=embed)

    async def create_now_playing_embed(self, source):
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
        return embed

    # Disconnect 명령어
    @app_commands.command(name='disconnect', description='봇을 음성 채널에서 내보냅니다')
    async def disconnect_command(self, interaction: discord.Interaction):
        await self.disconnect_bot(interaction)

    async def disconnect_bot(self, interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            if interaction.guild.id in self.queue:
                self.queue[interaction.guild.id].clear()
            if interaction.guild.id in self.current:
                del self.current[interaction.guild.id]
            await interaction.response.send_message("음성 채널에서 나갔습니다.")
        else:
            await interaction.response.send_message("이미 음성 채널에서 나와있습니다.", ephemeral=True)

    # Help 명령어
    @app_commands.command(name='help', description='봇의 명령어 목록과 사용법을 보여줍니다')
    async def help_command(self, interaction: discord.Interaction):
        await self.show_help(interaction)

    async def show_help(self, interaction: discord.Interaction):
        embed = await self.create_help_embed()
        await interaction.response.send_message(embed=embed)

    async def create_help_embed(self):
        embed = discord.Embed(
            title="음악 봇 도움말",
            description="모든 명령어는 슬래시(/) 명령어로 동작합니다.",
            color=discord.Color.blue()
        )

        commands = {
            "- 음악 관련 명령어": {
                "/play, /p, /재생 [노래제목/URL]": "음악을 재생합니다. 유튜브 링크나 검색어를 입력할 수 있습니다."
                                             "\n 제목으로 검색하는경우 자동으로 '가사'를 붙여 검색하므로 제목만 작성해주세요. "
                                             "\n '가사'를 붙이지 않고 검색하고 싶다면 /mv 명령어를 사용하세요.",
                "/pause": "현재 재생 중인 음악을 일시정지합니다.",
                "/resume": "일시정지된 음악을 다시 재생합니다.",
                "/skip": "현재 재생 중인 곡을 건너뜁니다.",
                "/stop": "재생을 중지하고 대기열을 초기화합니다.",
            },
            "- 재생목록 관련 명령어": {
                "/queue": "현재 재생 대기열을 보여줍니다.",
                "/clear": "재생 대기열을 초기화합니다.",
                "/np": "현재 재생 중인 곡의 정보를 보여줍니다."
            },
            "- 봇 제어관련 명령어": {
                "/help": "도움말을 보여줍니다.",
                "/status": "현재 서버의 상태를 보여줍니다.",
                "/join": "음악을 재생하면 어차피 들어오지만 그냥 보고싶을때 사용합니다.",
                "/disconnect": "봇을 음성 채널에서 내보냅니다."
            }
        }

        for category, items in commands.items():
            command_text = "\n".join([f"**{cmd}**\n{desc}" for cmd, desc in items.items()])
            embed.add_field(name=category, value=command_text, inline=False)

        embed.add_field(
            name="📞 개발자 연락처",
            value=f"문의사항이나 버그 제보는 아래 링크로 연락해주세요:\n"
                  f"• Discord: {discord_tag}\n"
                  f"• GitHub: {github_profile}\n"
                  "※ 지나치게 많거나 빠른 DM은 자동으로 차단될 수 있습니다.",
            inline=False
        )

        embed.set_footer(text="24시간 음악과 함께하는 즐거움! 🎵")
        return embed

    # Status 명령어
    @app_commands.command(name='status', description='현재 서버상태를 보여줍니다')
    async def status_command(self, interaction: discord.Interaction):
        await self.show_server_status(interaction)

    async def show_server_status(self, interaction: discord.Interaction):
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()

        cpu_status = "나쁨" if cpu_usage >= 80 else "좋음"
        memory_status = "나쁨" if memory_info.percent >= 80 else "좋음"
        server_state = "서버가 아파요 ㅠㅠ" if cpu_status == "나쁨" or memory_status == "나쁨" else "서버가 왠일로 괜찮네요"

        embed = await self.create_status_embed(cpu_usage, memory_info, server_state)
        await interaction.response.send_message(embed=embed)

    async def create_status_embed(self, cpu_usage, memory_info, server_state):
        embed_color = discord.Color.red() if server_state == "나쁨" else discord.Color.green()
        embed = discord.Embed(
            title="서버 상태",
            description="서버의 CPU와 메모리 상태입니다.",
            color=embed_color
        )

        embed.add_field(name="CPU 사용량", value=f"{cpu_usage}%", inline=False)
        embed.add_field(name="메모리 사용량", value=f"{memory_info.percent}%", inline=False)
        embed.add_field(name=f"{server_state}", value=' ', inline=False)

        return embed

    @app_commands.command(name='version', description='현재 버전과 릴리즈노트를 확인합니다')
    async def version_command(self, interaction: discord.Interaction):
        await self.show_version_info(interaction)

    async def show_version_info(self, interaction: discord.Interaction):
        try:
            version_data = await self.get_version_data()
            embed = await self.create_version_embed(version_data)
            await interaction.response.send_message(embed=embed)
        except FileNotFoundError:
            await interaction.response.send_message("버전 정보를 찾을 수 없습니다.", ephemeral=True)
        except json.JSONDecodeError:
            await interaction.response.send_message("버전 정보 파일을 읽는 중 오류가 발생했습니다.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"오류가 발생했습니다: {str(e)}", ephemeral=True)

    async def get_version_data(self):
        package_path = os.path.join(os.path.dirname(__file__), 'package.json')
        changelog_path = os.path.join(os.path.dirname(__file__), 'CHANGELOG.md')

        try:
            with open(package_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
                current_version = package_data.get('version', '버전 정보 없음')
                repo_url = package_data.get('repository', {}).get('url', '')

                if repo_url.startswith('git+'):
                    repo_url = repo_url[4:]
                if repo_url.endswith('.git'):
                    repo_url = repo_url[:-4]

            with open(changelog_path, 'r', encoding='utf-8') as f:
                changelog_content = f.read()
                version_info = await self.parse_changelog(changelog_content, current_version)

            return {
                'current_version': current_version,
                'repo_url': repo_url,
                'changelog_content': changelog_content,
                **version_info
            }
        except Exception as e:
            raise Exception(f"버전 정보를 가져오는 중 오류가 발생했습니다: {str(e)}")

    async def parse_changelog(self, changelog_content, current_version):
        version_section = ""
        update_date = None
        lines = changelog_content.split('\n')
        recording = False

        for line in lines:
            if f"[{current_version}]" in line:
                recording = True
                date_match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', line)
                if date_match:
                    update_date = date_match.group(1)
                    try:
                        date_obj = datetime.strptime(update_date, '%Y-%m-%d')
                        update_date = date_obj.strftime('%Y년 %m월 %d일')
                    except ValueError:
                        pass
                continue
            elif recording and line.startswith('## ['):
                break
            elif recording and line.strip():
                version_section += line + '\n'

        version_section = version_section.strip()
        if version_section and len(version_section) > 300:
            version_section = version_section[:297] + "..."
        version_section = version_section.replace("###", ">")

        return {
            'version_section': version_section,
            'update_date': update_date
        }

    async def create_version_embed(self, version_data):
        embed = discord.Embed(
            title="디스코드 봇 버전 정보",
            description=f"현재 버전: v{version_data['current_version']}",
            color=discord.Color.blue()
        )

        changelog_url = f"{version_data['repo_url']}/blob/main/CHANGELOG.md"
        embed.add_field(
            name="릴리즈 노트",
            value=f"[v{version_data['current_version']} 릴리즈 노트 보기]({changelog_url})",
            inline=False
        )

        if version_data['version_section']:
            embed.add_field(
                name="최신 변경사항",
                value=version_data['version_section'],
                inline=False
            )

        footer_text = f"최근 업데이트: {version_data['update_date']}" if version_data['update_date'] else "업데이트 날짜 정보 없음"
        embed.set_footer(text=footer_text)

        return embed

    @app_commands.command(name='채널셋업', description='음악 봇 컨트롤 패널을 생성합니다')
    @app_commands.default_permissions(administrator=True)
    async def setup_channel_command(self, interaction: discord.Interaction):
        await self.create_control_panel(interaction)

    async def create_control_panel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("이 명령어는 관리자 권한이 필요합니다.", ephemeral=True)
            return

        channel = await self.create_music_channel(interaction)
        embed = await self.create_panel_embed()
        view = MusicControlView(self.bot)

        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"컨트롤 패널이 {channel.mention}에 생성되었습니다!", ephemeral=True)

    async def create_music_channel(self, interaction: discord.Interaction):
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                send_messages=False,
                add_reactions=False
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                send_messages=True,
                embed_links=True,
                add_reactions=True,
                manage_messages=True
            )
        }

        return await interaction.guild.create_text_channel(
            '알로롱-음악채널',
            overwrites=overwrites,
            reason="Music bot control panel"
        )

    async def create_panel_embed(self):
        embed = discord.Embed(
            title="알로롱 - 음악채널",
            description="아래 버튼을 눌러 음악 봇을 제어할 수 있습니다.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="99.9%의 업타임 보장 🚀",
            value="봇 재시작 시에도 음악이 끊기지 않으며, 음질과 최적화를 위해 데일리 업데이트를 제공합니다.",
            inline=False
        )

        embed.add_field(
            name="최적의 사용자 편의를 제공하는 UI 🎯",
            value="유저가 친숙한 편하게 최소한의 동작으로 기능을 사용할 수 있도록 설계했습니다.",
            inline=False
        )

        embed.add_field(
            name="호환성부터 보장된 고품질 서비스를 유지합니다 ❤️",
            value="주원자분들의 지원으로 모든 유저가 무료로 최상의 기능을 누릴 수 있습니다. 작은 후원도 큰 힘이 됩니다.",
            inline=False
        )

        return embed

        # 음악 재생 로직

    async def play_music(self, interaction: discord.Interaction, query: str):
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
                if not '가사' in query:
                    query = query + ' 가사'
                query = f"ytsearch:{query}"


            # 플레이리스트 정보를 가져옴
            playlist_data = await self.loop.run_in_executor(None, lambda: ytdlp.extract_info(query, download=False))
            print(playlist_data)

            # 제목으로 검색하면 단일곡이어도 entries가 포함되는 경우 존재
            if 'playlist_count' in playlist_data and playlist_data['playlist_count'] > 1:
                # 재생목록인 경우
                await interaction.followup.send(f'재생목록을 불러오는 중입니다...')
                first_song_processed = False
                print("case1")
                for entry in playlist_data['entries']:
                    if entry:
                        try:
                            webpage_url = entry.get('url') or entry.get('webpage_url')
                            if not webpage_url:
                                continue

                            video_options = ytdlp_format_options.copy()
                            video_options['extract_flat'] = False

                            with yt_dlp.YoutubeDL(video_options) as ydl:
                                entry_data = await self.loop.run_in_executor(None,
                                                                             lambda: ydl.extract_info(webpage_url,
                                                                                                      download=False))

                            if entry_data:
                                source = YTDLPSource(discord.FFmpegPCMAudio(
                                    entry_data['url'],
                                    **ffmpeg_options
                                ), data=entry_data)

                                self.queue[interaction.guild.id].append(source)

                                # 첫 번째 곡이 처리되면 바로 재생 시작
                                if not first_song_processed:
                                    first_song_processed = True
                                    if not interaction.guild.voice_client.is_playing():
                                        await self.play_next(interaction)

                        except Exception as e:
                            print(f"Error processing playlist entry: {e}")
                            continue

                await interaction.followup.send(f'재생목록에 {len(self.queue[interaction.guild.id])}개의 곡이 추가되었습니다.')
            else:
                print("case2")
                # 단일 영상인 경우
                if 'entries' in playlist_data:
                    query = playlist_data['entries'][0]['url']
                data = await self.loop.run_in_executor(None, lambda: ytdlp.extract_info(query, download=False))
                url = data['url']
                # print(url)
                # data = await self.loop.run_in_executor(None, lambda: ytdlp.extract_info(url, download=False))
                if data:
                    source = YTDLPSource(discord.FFmpegPCMAudio(
                        data['url'],
                        **ffmpeg_options
                    ), data=data)


                    print("case3")

                    self.queue[interaction.guild.id].append(source)

                    embed = discord.Embed(
                        title="대기열에 추가됨",
                        description=f"[{source.title}]({source.webpage_url})",
                        color=discord.Color.green()
                    )
                    print("case4")
                    if source.thumbnail:
                        embed.set_thumbnail(url=source.thumbnail)
                    if source.duration:
                        embed.add_field(
                            name="길이",
                            value=f"{int(source.duration // 60)}:{int(source.duration % 60):02d}"
                        )
                    await interaction.followup.send(embed=embed)

                    if not interaction.guild.voice_client.is_playing():
                        await self.play_next(interaction)

        except Exception as e:
            await interaction.followup.send(f'오류가 발생했습니다: {str(e)}')

    async def play_next(self, interaction: discord.Interaction):
        # 먼저 voice client가 여전히 연결되어 있는지 확인
        if not interaction.guild.voice_client:
            return

        if not self.queue[interaction.guild.id]:
            await interaction.followup.send("재생할 곡이 없습니다. 3분 내에 음악이 추가되지 않으면 자동으로 연결이 종료됩니다.")

            try:
                # 3분 대기
                await asyncio.sleep(180)
                # 3분 후에도 대기열이 비어있고 재생 중이 아니며, 여전히 연결되어 있는지 확인
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

    # 각 명령어는 공통 로직을 호출합니다
    @app_commands.command(name='play', description='YouTube URL 또는 검색어로 음악을 재생합니다')
    @app_commands.describe(query='재생할 노래의 제목이나 URL을 입력하세요')
    async def play(self, interaction: discord.Interaction, query: str):
        await self.play_music(interaction, query)

    @app_commands.command(name='p', description='YouTube URL 또는 검색어로 음악을 재생합니다')
    @app_commands.describe(query='재생할 노래의 제목이나 URL을 입력하세요')
    async def play_alias_p(self, interaction: discord.Interaction, query: str):
        await self.play_music(interaction, query)

    @app_commands.command(name='ㅔ', description='YouTube URL 또는 검색어로 음악을 재생합니다')
    @app_commands.describe(query='재생할 노래의 제목이나 URL을 입력하세요')
    async def play_alias_ko(self, interaction: discord.Interaction, query: str):
        await self.play_music(interaction, query)






class MusicControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="대기열", style=discord.ButtonStyle.primary, emoji="📋", custom_id="queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        print('show_queue')
        await music_bot.show_queue(interaction)

    @discord.ui.button(label="인기차트", style=discord.ButtonStyle.success, emoji="⭐", custom_id="playlist")
    async def playlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_popular_chart(interaction)

    @discord.ui.button(label="빌보드", style=discord.ButtonStyle.primary, emoji="🎵", custom_id="billboard")
    async def billboard_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_billboard_chart(interaction)

    @discord.ui.button(label="멜론차트", style=discord.ButtonStyle.secondary, emoji="🎶", custom_id="melon")
    async def melon_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_melon_chart(interaction)

    @discord.ui.button(label="활동 포시", style=discord.ButtonStyle.primary, emoji="🎵", custom_id="share")
    async def share_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_activity_share(interaction)

    @discord.ui.button(label="명령어 보기", style=discord.ButtonStyle.secondary, emoji="📖", custom_id="commands")
    async def commands_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.help_command(interaction)

    @discord.ui.button(label="후원 리워드", style=discord.ButtonStyle.primary, emoji="✨", custom_id="premium")
    async def premium_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_premium_rewards(interaction)

    @discord.ui.button(label="노래 FAQ", style=discord.ButtonStyle.danger, emoji="❓", custom_id="faq")
    async def faq_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_faq(interaction)

    @discord.ui.button(label="음악 추천받기", style=discord.ButtonStyle.success, emoji="🎵", custom_id="recommend")
    async def recommend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_bot = self.bot.get_cog('MusicBot')
        await music_bot.show_music_recommendations(interaction)


async def setup(bot: commands.Bot):

    music_bot = MusicBot(bot)
    await bot.add_cog(music_bot)



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
            try:
                print("명령어 동기화 중...")
                synced = await self.tree.sync()
                print(synced)
                print(f"{len(synced)}개의 명령어 동기화 완료")
            except Exception as e:
                print(f"명령어 동기화 중 오류 발생: {e}")

    bot = MusicBotClient()

    @bot.event
    async def on_ready():
        print(f'봇이 준비되었습니다! {bot.user}로 로그인됨')
        await bot.change_presence(activity=discord.Game(name="개발"))

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())