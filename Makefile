.PHONY: install migrate seed run test lint shell db-shell docker-up docker-down

install:
	pip install -r requirements/dev.txt

migrate:
	python manage.py migrate

makemigrations:
	python manage.py makemigrations

seed:
	python manage.py loaddata fixtures/initial.json || true

run:
	python manage.py runserver 0.0.0.0:8000

test:
	python -m pytest tests/ -v --ds=config.settings.dev

lint:
	ruff check .

format:
	ruff format .

shell:
	python manage.py shell

db-shell:
	python manage.py dbshell

docker-up:
	docker-compose -f docker-compose.dev.yml up --build

docker-down:
	docker-compose -f docker-compose.dev.yml down

docker-logs:
	docker-compose -f docker-compose.dev.yml logs -f

celery-worker:
	celery -A config worker --loglevel=info --settings=config.settings.dev

celery-beat:
	celery -A config beat --loglevel=info --settings=config.settings.dev

createsuperuser:
	python manage.py createsuperuser

collectstatic:
	python manage.py collectstatic --noinput
