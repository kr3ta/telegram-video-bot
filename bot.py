import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv


# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env")


# Создаём бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
MAX_TELEGRAM_VIDEO_BYTES = 48_000_000


def inspect_video(path: Path) -> dict | None:
    """Возвращает сведения о видеопотоке, если установлен ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        print("ffprobe не найден; разрешение и кодеки проверить не удалось.")
        return None

    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe_data = json.loads(result.stdout)
    streams = probe_data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    if video:
        print(
            "Полученное видео: "
            f"{video.get('width')}x{video.get('height')}, "
            f"видеокодек {video.get('codec_name')}, "
            f"аудиокодек {audio.get('codec_name') if audio else 'нет'}"
        )
    else:
        print("ffprobe не обнаружил видеопоток.")

    duration = float(probe_data.get("format", {}).get("duration", 0) or 0)
    return {"video": video, "audio": audio, "duration": duration}


def make_telegram_mp4(path: Path, stream_info: dict | None) -> Path:
    """Создаёт MP4 для Telegram и сжимает его при превышении лимита размера."""
    video = stream_info.get("video") if stream_info else None
    audio = stream_info.get("audio") if stream_info else None
    codecs_are_compatible = (
        video is not None
        and video.get("codec_name") == "h264"
        and (audio is None or audio.get("codec_name") == "aac")
    )

    needs_conversion = not (
        path.suffix.lower() in {".mp4", ".m4v"}
        and (codecs_are_compatible or stream_info is None)
    )
    needs_compression = path.stat().st_size > MAX_TELEGRAM_VIDEO_BYTES
    if not needs_conversion and not needs_compression:
        return path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg не найден; невозможно подготовить видео для Telegram")

    if needs_conversion:
        mp4_path = path.with_name(f"{path.stem}_telegram.mp4")
        print(f"Подготавливаю MP4: {path.name} → {mp4_path.name} (без изменения разрешения).")
        subprocess.run(
            [
                ffmpeg,
                "-i", str(path),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-y", str(mp4_path),
            ],
            check=True,
        )
    else:
        mp4_path = path

    if mp4_path.stat().st_size <= MAX_TELEGRAM_VIDEO_BYTES:
        return mp4_path

    duration = stream_info.get("duration", 0) if stream_info else 0
    if duration <= 0:
        raise RuntimeError("Файл больше лимита Telegram, а длительность видео определить не удалось")

    # Целимся в 48 MB, оставляя запас до лимита Telegram в 50 MB.
    audio_bitrate_kbps = 128
    total_bitrate_kbps = MAX_TELEGRAM_VIDEO_BYTES * 8 / duration / 1000 * 0.95
    video_bitrate_kbps = max(100, int(total_bitrate_kbps - audio_bitrate_kbps))
    compressed_path = mp4_path.with_name(f"{mp4_path.stem}_compressed.mp4")
    passlog_path = compressed_path.with_suffix("")
    print(
        f"Файл весит {mp4_path.stat().st_size / 1_000_000:.1f} MB; "
        f"сжимаю до лимита Telegram, сохраняя разрешение "
        f"(видеобитрейт {video_bitrate_kbps} kb/s)."
    )
    subprocess.run(
        [
            ffmpeg,
            "-y", "-i", str(mp4_path),
            "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{video_bitrate_kbps}k",
            "-pass", "1", "-passlogfile", str(passlog_path),
            "-f", "null", os.devnull,
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-y", "-i", str(mp4_path),
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{video_bitrate_kbps}k",
            "-pass", "2", "-passlogfile", str(passlog_path),
            "-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k",
            "-movflags", "+faststart",
            str(compressed_path),
        ],
        check=True,
    )
    if compressed_path.stat().st_size > MAX_TELEGRAM_VIDEO_BYTES:
        raise RuntimeError(
            f"Сжатое видео всё ещё больше лимита Telegram: "
            f"{compressed_path.stat().st_size / 1_000_000:.1f} MB"
        )
    print(f"После сжатия: {compressed_path.stat().st_size / 1_000_000:.1f} MB.")
    return compressed_path


# Обработчик сообщений
@dp.message()
async def message_handler(message: Message):
    url = message.text

    # Проверяем ссылку
    if not url or ("youtube.com" not in url and "youtu.be" not in url):
        await message.answer("Пришли ссылку на видео с YouTube 🙂")
        return

    await message.answer("Принял, качаю ⏳")

    try:
        # Для каждой загрузки создаётся отдельная временная папка
        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")

            # Сначала пробуем MP4/H.264 + M4A/AAC, затем лучшие потоки до 1080p.
            format_selector = (
                "bestvideo[height<=1080][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            )
            subprocess.run(
                [
                    "yt-dlp",
                    "--js-runtimes", "node",
                    "--verbose",
                    "-f", format_selector,
                    "-o", output_template,
                    url,
                ],
                check=True,
            )

            # yt-dlp может сохранить MP4, WebM или другой контейнер после слияния.
            media_extensions = {".mp4", ".m4v", ".mkv", ".webm", ".mov"}
            downloaded_files = [
                path for path in Path(temp_dir).iterdir()
                if path.is_file() and path.suffix.lower() in media_extensions
            ]
            if not downloaded_files:
                await message.answer("Не нашёл файл после скачивания. Попробуй ещё раз.")
                return

            video_file = max(downloaded_files, key=lambda path: path.stat().st_size)
            print(f"yt-dlp сохранил файл: {video_file.name}")

            stream_info = inspect_video(video_file)
            video_file = make_telegram_mp4(video_file, stream_info)

            # Проверяем разрешение ещё раз после подготовки файла для Telegram.
            inspect_video(video_file)

            await message.answer_video(
                video=FSInputFile(video_file),
                caption="Держи 👇",
            )

        print("Временные файлы удалены.")

    except Exception as e:
        print(f"Ошибка обработки видео: {e!r}")
        try:
            await message.answer("Не получилось скачать видео 😕 Попробуй ещё раз чуть позже.")
        except Exception as notify_error:
            # Ошибка Telegram здесь вторичная; исходная ошибка уже записана выше.
            print(f"Не удалось отправить сообщение об ошибке в Telegram: {notify_error!r}")


# Запуск бота
async def main():
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
