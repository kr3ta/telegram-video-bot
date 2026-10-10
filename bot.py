import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher
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


# Обработчик сообщений
# Обработчик сообщений
@dp.message()
async def message_handler(message: Message):
    url = message.text

    # Проверяем ссылку
    if not url or ("youtube.com" not in url and "youtu.be" not in url):
        await message.answer("Пришли ссылку на YouTube-видео.")
        return

    await message.answer("⏳ Скачиваю видео...")

    try:
        # Создаём отдельную временную папку для этой загрузки
        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")

            # Скачиваем видео
            subprocess.run(
                [
                    "yt-dlp",
                    "--js-runtimes", "node",
                    "-f", "bestvideo[height<=360]+bestaudio/best[height<=360]",
                    "-o", output_template,
                    url,
                ],
                check=True,
            )

            # Ищем файл, созданный именно этой загрузкой
            downloaded_files = [
                path
                for path in Path(temp_dir).iterdir()
                if path.is_file()
            ]

            if not downloaded_files:
                await message.answer("Видео скачалось, но файл не найден.")
                return

            video_file = downloaded_files[0]

            # Если скачался WebM, конвертируем его в MP4
            if video_file.suffix.lower() == ".webm":
                mp4_file = video_file.with_suffix(".mp4")

                subprocess.run(
                    [
                        "ffmpeg",
                        "-i", str(video_file),
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        "-y",
                        str(mp4_file),
                    ],
                    check=True,
                )

                video_file = mp4_file

            # Отправляем видео в Telegram
            await message.answer_video(
                video=FSInputFile(video_file),
                caption="Готово! Видео скачано."
            )

        # После выхода из TemporaryDirectory папка и файлы удаляются автоматически
        print("Временные файлы удалены.")

    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("Не удалось скачать или отправить видео.")

        # Скачиваем видео
        subprocess.run(
            [
                "yt-dlp",
                "--js-runtimes", "node",
                "-f", "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]",
                "-o", "downloads/%(title)s.%(ext)s",
                url,
            ],
            check=True,
        )

        # Ищем скачанный MP4-файл
        files = glob.glob("*.mp4")

        if not files:
            await message.answer("Видео скачалось, но файл не найден.")
            return

        video_file = files[-1]

        # Отправляем видео в Telegram
        await message.answer_video(
            video=FSInputFile(video_file),
            caption="На хавай, скачал"
        )

    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("Не удалось скачать видео.")

    finally:
        # Удаляем временный файл после завершения работы
        if video_file and os.path.exists(video_file):
            os.remove(video_file)
            print(f"Временный файл удалён: {video_file}")


# Запуск бота
async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())