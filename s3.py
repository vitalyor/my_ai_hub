import asyncio
import aioboto3
import os
import boto3
from urllib.parse import urlsplit
from botocore.config import Config
from anyio import fail_after
from dotenv import load_dotenv
from smart_open import open as sopen

load_dotenv()


S3_ENDPOINT = os.getenv("S3_ENDPOINT")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_URL_TTL = int(os.getenv("S3_URL_TTL", "3600"))  # seconds


class S3Client:
    def __init__(
        self,
    ):
        self.access_key = AWS_ACCESS_KEY
        self.secret_key = AWS_SECRET_KEY
        self.endpoint_url = S3_ENDPOINT.rstrip("/")
        self.bucket_name = S3_BUCKET
        self.region_name = AWS_REGION

    async def upload_file(
        self,
        file_path: str,
        file_url: str,
        prediction_id: str,
    ):
        if file_path != None:
            session = aioboto3.Session()
            object_name = file_path.split("/")[-1]
            async with session.client(
                "s3",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
            ) as client:
                await client.upload_file(file_path, self.bucket_name, object_name)
            # presigned URL after upload
            url = await self.get_file_url(object_name, expires_in=S3_URL_TTL)
            return url
        elif file_url != None:
            path = urlsplit(file_url).path
            ext = os.path.splitext(path)[1] or ".bin"
            object_name = f"{prediction_id}{ext}"

            await asyncio.to_thread(
                upload_via_smart_open,
                file_url,
                self.bucket_name,
                object_name,
                self.endpoint_url,
                self.access_key,
                self.secret_key,
                self.region_name,
            )

            # проверяем, что объект действительно записан
            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name,
                config=Config(
                    s3={"addressing_style": "path"}, signature_version="s3v4"
                ),
            )
            s3.head_object(Bucket=self.bucket_name, Key=object_name)
            url = await self.get_file_url(object_name, expires_in=S3_URL_TTL)
            return url
        else:
            print("Ошибка")

    async def get_file_url(
        self, object_name: str, expires_in: int | None = None
    ) -> str:
        """
        Получить ссылку на файл:
        - если expires_in не указан -> формируется публичный URL (если объект доступен публично)
        - если expires_in указан -> генерируется временная (presigned) ссылка
        """
        if not expires_in:
            return f"{self.endpoint_url}/{self.bucket_name}/{object_name}"

        session = aioboto3.Session()
        async with session.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            url = await client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": object_name},
                ExpiresIn=expires_in,
            )
            return url


def upload_via_smart_open(
    file_url, bucket, key, endpoint, access_key, secret_key, region
):
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,  # например, https://s3.cloud.ru
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,  # ru-central-1
        config=Config(
            s3={"addressing_style": "path"},  # критично для non-AWS
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    with sopen(file_url, "rb") as fin, sopen(
        f"s3://{bucket}/{key}", "wb", transport_params={"client": s3_client}
    ) as fout:
        for chunk in iter(lambda: fin.read(1024 * 1024), b""):
            fout.write(chunk)
