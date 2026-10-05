import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile
from dotenv import load_dotenv


# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env")


# Создаём бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Обработчик команды /start
@dp.message()
async def message_handler(message: Message):
    url = message.text

    if not url or "youtube.com" not in url and "youtu.be" not in url:
        await message.answer("Дурак дай на ютуб ссылку")

    await message.answer("Скачиваю видео")

    try:
        import subprocess

        subprocess.run(
            [
                "yt-dlp",
                "--js-runtimes", "node",
                "-f", "134+140-1",
                url,
            ],
            check=True,
        )

        import glob

        files = glob.glob("*.mp4")

        if not files:
            await message.answer("Видео скачалось, но файл не найден.")
            return

        video_file = files[-1]

        await message.answer_video(
            video=FSInputFile(video_file),
            caption="На хавай, скачал"
        )

    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("Не удалось скачать видео.")


# Обработчик обычных сообщений
@dp.message()
async def message_handler(message: Message):
    await message.answer(
        "Да да я вижу сообщенние но пока ниче не умею\n"
    )


# Запуск бота
async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())