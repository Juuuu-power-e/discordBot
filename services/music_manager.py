import yt_dlp
import discord
from typing import Dict, List, Optional, Any
import asyncio

from config.bot_config import BotConfig
from models.music_source import YTDLPSource
from utils.exceptions import MusicSourceError


class MusicManager:
    def __init__(self, config: BotConfig):
        self.config = config
        self.ytdlp = yt_dlp.YoutubeDL(config.YTDLP_FORMAT_OPTIONS)
        self.queue: Dict[int, List[YTDLPSource]] = {}
        self.current: Dict[int, YTDLPSource] = {}

    async def process_query(self, query: str, loop) -> List[YTDLPSource]:
        """사용자 쿼리 처리 (URL 또는 검색어)"""
        try:
            # URL이 아닌 경우 검색어로 처리
            if not any(s in query for s in ['youtube.com', 'youtu.be']):
                # 뮤직비디오를 제외하기 위해 {검색어}+가사로 검색
                if '가사' not in query:
                    query = f"{query} 가사"
                query = f"ytsearch:{query}"

            # 플레이리스트/영상 정보 가져오기
            playlist_data = await loop.run_in_executor(
                None,
                lambda: self.ytdlp.extract_info(query, download=False)
            )

            if not playlist_data:
                raise MusicSourceError("음원을 찾을 수 없습니다.")

            return await self.process_playlist_data(playlist_data, loop)

        except Exception as e:
            print(f"Error processing query: {e}")
            raise MusicSourceError(f"음원 처리 중 오류 발생: {str(e)}")

    async def process_playlist_data(self, playlist_data: Dict[str, Any], loop) -> List[YTDLPSource]:
        """플레이리스트 데이터 처리"""
        sources = []

        # 플레이리스트인 경우
        if 'entries' in playlist_data:
            entries = playlist_data['entries']
            for entry in entries:
                if entry:
                    source = await self.create_source_from_data(entry, loop)
                    if source:
                        sources.append(source)
        # 단일 영상인 경우
        else:
            source = await self.create_source_from_data(playlist_data, loop)
            if source:
                sources.append(source)

        return sources

    async def create_source_from_data(self, data: Dict[str, Any], loop) -> Optional[YTDLPSource]:
        """음원 소스 생성"""
        try:
            # 상세 정보가 필요한 경우 추가 정보 가져오기
            if not data.get('url'):
                webpage_url = data.get('webpage_url')
                if not webpage_url:
                    return None

                video_options = self.config.YTDLP_FORMAT_OPTIONS.copy()
                video_options['extract_flat'] = False

                with yt_dlp.YoutubeDL(video_options) as ydl:
                    data = await loop.run_in_executor(
                        None,
                        lambda: ydl.extract_info(webpage_url, download=False)
                    )

            if not data:
                return None

            # FFmpeg 오디오 소스 생성
            audio_source = discord.FFmpegPCMAudio(
                data['url'],
                **self.config.FFMPEG_OPTIONS
            )

            return YTDLPSource(audio_source, data=data)

        except Exception as e:
            print(f"Error creating source: {e}")
            return None

    def add_to_queue(self, guild_id: int, source: YTDLPSource):
        """대기열에 곡 추가"""
        if guild_id not in self.queue:
            self.queue[guild_id] = []
        self.queue[guild_id].append(source)

    def remove_from_queue(self, guild_id: int, index: int) -> Optional[YTDLPSource]:
        """대기열에서 특정 곡 제거"""
        if guild_id in self.queue and 0 <= index < len(self.queue[guild_id]):
            return self.queue[guild_id].pop(index)
        return None

    def clear_queue(self, guild_id: int):
        """대기열 초기화"""
        if guild_id in self.queue:
            self.queue[guild_id].clear()
        if guild_id in self.current:
            del self.current[guild_id]

    def get_queue(self, guild_id: int) -> List[YTDLPSource]:
        """현재 대기열 반환"""
        return self.queue.get(guild_id, [])

    def get_current(self, guild_id: int) -> Optional[YTDLPSource]:
        """현재 재생 중인 곡 정보 반환"""
        return self.current.get(guild_id)

    def set_current(self, guild_id: int, source: YTDLPSource):
        """현재 재생 중인 곡 설정"""
        self.current[guild_id] = source

    def get_queue_length(self, guild_id: int) -> int:
        """대기열 길이 반환"""
        return len(self.queue.get(guild_id, []))

    async def get_estimated_time(self, guild_id: int, position: int) -> Optional[float]:
        """특정 위치의 곡까지 예상 재생 시간 계산"""
        if guild_id not in self.queue or position >= len(self.queue[guild_id]):
            return None

        total_time = 0
        current = self.current.get(guild_id)

        if current and current.duration:
            total_time += current.duration

        for i in range(position):
            source = self.queue[guild_id][i]
            if source.duration:
                total_time += source.duration

        return total_time

    async def cleanup(self, guild_id: int):
        """리소스 정리"""
        self.clear_queue(guild_id)
        if guild_id in self.current:
            del self.current[guild_id]