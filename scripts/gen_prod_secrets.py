"""Генерация прод-секретов (Этап 9.1, ТЗ 13.2).

Заполняет поля `<GEN:...>` шаблона .env.prod.template и создаёт s3-prod.json
из docker/s3-prod.json.example. app-ключи S3 синхронны в обоих файлах
(приложение и SeaweedFS должны видеть одну пару access/secret).

Использование (в контейнере web или на хосте с python3 + cryptography):
    python scripts/gen_prod_secrets.py                       # .env.prod.template -> .env, example -> s3-prod.json
    python scripts/gen_prod_secrets.py --env-out FILE --s3-out FILE
    python scripts/gen_prod_secrets.py --dry-run             # значения секретов в stdout, ничего не писать

Не трогает пользовательские плейсхолдеры `<...>` (домен, SMTP, OAuth, токены
ботов) — их заполняет человек. Готовые файлы содержат секреты: chmod 600,
в git не попадают (оба пути в .gitignore). s3-prod.json пишется UTF-8 БЕЗ BOM
(урок docs/deployment.md: BOM ломает чтение конфига SeaweedFS).
"""

import argparse
import base64
import json
import os
import re
import secrets
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALNUM_UPPER = string.ascii_uppercase + string.digits
ALNUM = string.ascii_letters + string.digits


def _token(alphabet: str, length: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def secret_key() -> str:
    # token_urlsafe = A-Za-z0-9-_ (base64url, без `=` padding): безопасно и для
    # Django (важны длина и случайность, не алфавит), и для shell `source .env`,
    # и для compose env_file/Dockerfile (не ломается на `# $ ( ) & *`).
    # Аналог get_random_secret_key без спец-символов.
    return secrets.token_urlsafe(48)


def fernet_key() -> str:
    try:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()
    except ImportError:
        # Fernet-ключ = 32 случайных байта в url-safe base64 (то же определение).
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def generate() -> dict[str, str]:
    app_access = _token(ALNUM_UPPER, 20)
    app_secret = _token(ALNUM, 40)
    return {
        "SECRET_KEY": secret_key(),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "BOT_TOKEN_PEPPER": secrets.token_urlsafe(32),
        "FERNET_KEY": fernet_key(),
        "S3_ACCESS_KEY": app_access,
        "S3_SECRET_KEY": app_secret,
        # только в s3-prod.json:
        "S3_ADMIN_ACCESS_KEY": _token(ALNUM_UPPER, 20),
        "S3_ADMIN_SECRET_KEY": _token(ALNUM, 40),
        "S3_SIGNING_KEY": _token(ALNUM, 40),
    }


def fill_env(template_path: str, out_path: str, values: dict[str, str], force: bool) -> list[str]:
    with open(template_path, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    gen_placeholder = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=\s*<[^>]*>\s*$")
    leftovers: list[str] = []
    out: list[str] = []
    for line in lines:
        m = gen_placeholder.match(line.rstrip("\n"))
        if m:
            key = m.group(1)
            if key in values:
                out.append(f"{key}={values[key]}\n")
                continue
        # не сгенерировано → если в значении остался `<...>` (целиком или внутри,
        # напр. ghcr.io/<OWNER>/…, noreply@<ДОМЕН>) — напомнить пользователю.
        km = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.rstrip("\n"))
        if km and re.search(r"<[^>]+>", km.group(2)):
            leftovers.append(km.group(1))
        out.append(line)
    _write_protected(out_path, "".join(out), force)
    return leftovers


def fill_s3(example_path: str, out_path: str, values: dict[str, str], force: bool) -> None:
    with open(example_path, encoding="utf-8-sig") as f:
        config = json.load(f)
    config["signingKey"] = values["S3_SIGNING_KEY"]
    creds = {
        "app": (values["S3_ACCESS_KEY"], values["S3_SECRET_KEY"]),
        "admin": (values["S3_ADMIN_ACCESS_KEY"], values["S3_ADMIN_SECRET_KEY"]),
    }
    for identity in config.get("identities", []):
        access, secret = creds.get(identity.get("name"), ("", ""))
        for entry in identity.get("credentials", []):
            entry["accessKey"] = access
            entry["secretKey"] = secret
    # utf-8 (не utf-8-sig): без BOM — иначе SeaweedFS не читает конфиг.
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    if not force:
        os.chmod(out_path, 0o600)


def _write_protected(path: str, text: str, force: bool) -> None:
    if os.path.exists(path) and not force:
        sys.exit(f"{path} уже существует — не перезаписываем (секреты!) ; --force или другой --*-out")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if not force:
        os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-template", default=os.path.join(ROOT, ".env.prod.template"))
    parser.add_argument("--env-out", default=os.path.join(ROOT, ".env"))
    parser.add_argument("--s3-example", default=os.path.join(ROOT, "docker", "s3-prod.json.example"))
    parser.add_argument("--s3-out", default=os.path.join(ROOT, "s3-prod.json"))
    parser.add_argument("--force", action="store_true", help="перезаписать существующие файлы")
    parser.add_argument("--dry-run", action="store_true", help="только показать сгенерированные значения")
    args = parser.parse_args()

    values = generate()
    if args.dry_run:
        for key, value in values.items():
            print(f"{key}={value}")
        return

    leftovers = fill_env(args.env_template, args.env_out, values, args.force)
    fill_s3(args.s3_example, args.s3_out, values, args.force)

    print(f"Записано: {args.env_out} (секреты вставлены), {args.s3_out} (UTF-8 без BOM, chmod 600).")
    if leftovers:
        print("Заполните вручную в " + args.env_out + ": " + ", ".join(leftovers))
    print("Проверка: python manage.py check --deploy (core.E001 не должен появляться).")


if __name__ == "__main__":
    main()
