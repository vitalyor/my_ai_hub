import time
from dotenv import load_dotenv
import replicate
import os
from s3 import S3Client
import asyncio

load_dotenv()

REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY")


client = replicate.Client(api_token=REPLICATE_API_KEY)


# --- Helper to detect Whisper-like output and extract transcription ---
def _as_whisper_transcription(output):
    """If output looks like Whisper (dict with 'transcription' and optional 'segments'),
    return the transcription string; otherwise return None."""
    if isinstance(output, dict):
        t = output.get("transcription")
        if isinstance(t, str) and t.strip():
            return t
    if isinstance(output, list) and output and isinstance(output[0], dict):
        # sometimes models wrap single dict in a list
        t = output[0].get("transcription")
        if isinstance(t, str) and t.strip():
            return t
    return None


async def upload_to_s3(file_path=None, file_url=None, prediction_id=None):
    s3_client = S3Client()
    url = await s3_client.upload_file(file_path, file_url, prediction_id)
    return url


# 1. Создаем prediction
prediction = client.predictions.create(
    "bytedance/seedance-1-pro",
    input={
        "fps": 24,
        "prompt": "The sun rises slowly between tall buildings. [Ground-level follow shot] Bicycle tires roll over a dew-covered street at dawn. The cyclist passes through dappled light under a bridge as the entire city gradually wakes up.",
        "duration": 3,
        "resolution": "480p",
        "aspect_ratio": "16:9",
        "camera_fixed": False
    }
)

# prediction.status будет "starting", "processing", "succeeded" и т.п.
while prediction.status not in ("succeeded", "failed"):
    print("Статус:", prediction.status)
    time.sleep(1)
    prediction = client.predictions.get(prediction.id)

if prediction.status == "succeeded":
    out = prediction.output
    # --- Whisper-specific: if model returned a dict with 'transcription' ---
    whisper_text = _as_whisper_transcription(out)
    if whisper_text is not None:
        print("\n=== TEXT OUTPUT (Whisper transcription) ===")
        print(whisper_text)
    else:
        # Если список и внутри ссылки — пройдёмся по всем
        urls = []
        if isinstance(out, list):
            for item in out:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    urls.append(item)
            # если список и там только один элемент-строка
            if not urls and len(out) == 1 and isinstance(out[0], str):
                urls = [out[0]]

        elif isinstance(out, str) and out.startswith(("http://", "https://")):
            urls = [out]

        if urls:
            # определяем тип по расширению
            for idx, u in enumerate(urls):
                ext = os.path.splitext(u.split("?")[0])[1].lower()
                if ext in (
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".gif",
                    ".bmp",
                    ".tiff",
                    ".mp4",
                    ".mov",
                    ".mkv",
                    ".avi",
                    ".webm",
                    ".mp3",
                    ".wav",
                    ".m4a",
                    ".flac",
                    ".ogg",
                ):
                    pid = f"{prediction.id}-{idx}" if len(urls) > 1 else prediction.id
                    presigned_url = asyncio.run(upload_to_s3(None, u, pid))
                    print(f"Presigned URL: {presigned_url}")
                else:
                    # считаем это текстовым
                    print(u)
        else:
            # fallback: выводим как текст
            print(out)

else:
    print("Ошибка:", prediction.error)

print("\n--- METRICS ---")
print(prediction.metrics)  # тут input_token_count, output_token_count и пр.