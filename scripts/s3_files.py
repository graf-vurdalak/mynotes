"""Миграция/бэкап файлов медиа между локальным media-каталогом и S3 (SeaweedFS).

Использование (из контейнера web, настройки из env S3_*):
    python scripts/s3_files.py push [SRC_DIR]   # локальные файлы -> бакет (существующие ключи пропускаются)
    python scripts/s3_files.py pull [DST_DIR]   # бакет -> локальные файлы (размер совпадает — пропуск)

Тот же push использовался для dev-переноса ./media; pull — базовая единица бэкапа
и восстановления. Идемпотентен: можно перезапускать на полутую миграцию.
"""

import os
import sys

import boto3
from botocore.client import Config


def _client():
    endpoint = os.environ.get("S3_ENDPOINT", "")
    if not endpoint:
        sys.exit("S3_ENDPOINT не задан — скрипт работает только при включённом S3-backend")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
        region_name=os.environ.get("S3_REGION") or "us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )


def _bucket():
    return os.environ.get("S3_BUCKET") or "mynotes"


def _default_dir():
    # /app/media в контейнере; вне контейнера — ./media рядом с репозиторием.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "media")


def push(src):
    c, b = _client(), _bucket()
    uploaded = skipped = 0
    for base, _dirs, files in os.walk(src):
        for fn in files:
            full = os.path.join(base, fn)
            key = os.path.relpath(full, src).replace(os.sep, "/")
            try:
                remote = c.head_object(Bucket=b, Key=key)
                if remote["ContentLength"] == os.path.getsize(full):
                    skipped += 1
                    continue
            except Exception:
                pass
            with open(full, "rb") as fh:
                c.upload_fileobj(fh, b, key)
            uploaded += 1
    print(f"push: загружено {uploaded}, пропущено (совпадает) {skipped}, бакет {b}")


def pull(dst):
    c, b = _client(), _bucket()
    os.makedirs(dst, exist_ok=True)
    downloaded = skipped = 0
    paginator = c.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=b):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            full = os.path.join(dst, *key.split("/"))
            if os.path.exists(full) and os.path.getsize(full) == size:
                skipped += 1
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            c.download_file(b, key, full)
            downloaded += 1
    print(f"pull: скачано {downloaded}, пропущено {skipped}, бакет {b} -> {dst}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("push", "pull"):
        sys.exit(__doc__)
    mode = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else _default_dir()
    (push if mode == "push" else pull)(target)


if __name__ == "__main__":
    main()
