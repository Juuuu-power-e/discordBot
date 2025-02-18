import asyncio
import os
from discord.ext import commands
from cogs.music_bot import MusicBot


async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix='!', intents=intents)
    await bot.add_cog(MusicBot(bot))

    token = os.getenv("DISCORD_BOT_TOKEN")
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())