"""Тесты глобального поиска /search/ (ТЗ 4.4, этап 7.7)."""

import datetime as dt
import uuid

import pytest
from django.db import connection
from django.urls import reverse

from apps.accounts.models import User
from apps.planner import services as pl_services
from apps.planner.models import Event, Project
from apps.vehicles.models import (
    Fine,
    FuelEntry,
    Insurance,
    PlannedEvent,
    Purchase,
    Service,
    Vehicle,
)

pytestmark = pytest.mark.django_db

TERM = "шиномонтаж"
ALL_KEYS = {
    "vehicle", "fuel", "purchase", "service", "fine",
    "insurance", "planned", "task", "event", "project",
}


@pytest.fixture
def user(db):
    return User.objects.create_user(email="srch@test.local", password="pass12345")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(email="srch2@test.local", password="pass12345")


@pytest.fixture
def scopes(user):
    return pl_services.guarantee_scopes(user)


@pytest.fixture
def personal(user, scopes):
    return scopes["personal"]


@pytest.fixture
def work(user, scopes):
    pl_services.ensure_statuses(user, scopes["work"])
    return scopes["work"]


@pytest.fixture
def vehicle(user):
    return Vehicle.objects.create(
        user=user, brand_custom="Toyota", model_custom="Camry",
        license_plate="А777АА 77", notes=f"{TERM} сезонный, баланс",
    )


@pytest.fixture
def project(user, work):
    return Project.objects.create(user=user, scope=work, title="Гараж", description=f"хранение и {TERM}")


@pytest.fixture
def data(vehicle, project, personal, work, user):
    FuelEntry.objects.create(
        user=user, vehicle=vehicle, fuel_date=dt.date(2026, 10, 1),
        odometer=1000, notes=f"оплата {TERM} на заправке",
    )
    Purchase.objects.create(
        user=user, vehicle=vehicle, title=f"Комплект для {TERM}",
        description="записан на сезон",
    )
    Service.objects.create(user=user, vehicle=vehicle, work_description=TERM)
    Fine.objects.create(user=user, vehicle=vehicle, description=f"проехал {TERM}")
    Insurance.objects.create(
        user=user, vehicle=vehicle, company=f"Компания {TERM}Страх",
    )
    PlannedEvent.objects.create(user=user, vehicle=vehicle, description=f"записаться на {TERM}")
    Event.objects.create(
        user=user, scope=work, project=project, title=f"Купить {TERM} комплект",
        tags=["сезонное"],
    )
    Event.objects.create(user=user, scope=personal, title=f"Записаться на {TERM}")


def _group_keys(response):
    return {g["key"] for g in response.context["groups"]}


def _all_hits(response):
    return [h for g in response.context["groups"] for h in g["hits"]]


def test_search_finds_all_entity_types(client, user, data):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM})
    assert response.status_code == 200
    assert _group_keys(response) == ALL_KEYS


def test_search_idor_only_own(client, user, other_user, data):
    v2 = Vehicle.objects.create(user=other_user, brand_custom="Lada")
    Purchase.objects.create(user=other_user, vehicle=v2, title=f"ЧУЖОЙ {TERM}")
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM})
    assert all("ЧУЖОЙ" not in h["title"] for h in _all_hits(response))


def test_search_type_filter(client, user, data):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM, "type": "fuel"})
    assert _group_keys(response) == {"fuel"}


def test_search_date_filter(client, user, data):
    client.force_login(user)
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    response = client.get(reverse("search:results"), {"q": TERM, "date_from": tomorrow})
    assert response.context["total"] == 0
    today = dt.date.today().isoformat()
    response = client.get(reverse("search:results"), {"q": TERM, "date_to": today})
    assert response.context["total"] > 0


def test_search_project_filter(client, user, data, project):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM, "project": str(project.pk)})
    task_hits = [h for g in response.context["groups"] if g["key"] == "task" for h in g["hits"]]
    assert len(task_hits) == 1
    response = client.get(reverse("search:results"), {"q": TERM, "project": str(uuid.uuid4())})
    assert not [h for g in response.context["groups"] if g["key"] == "task" for h in g["hits"]]


def test_search_stemmed_morphology(client, user, data):
    """tsvector(russian): дательный падеж находит именительный (ILIKE бы не смог)."""
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": "шиномонтажу"})
    titles = " ".join(h["title"] for h in _all_hits(response))
    assert TERM in titles  # исходная форма в тексте, запрос — другая падежная форма


def test_search_tag_exact(client, user, data):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": "сезонное"})
    assert "task" in _group_keys(response)


def test_search_highlight_in_title(client, user, data):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM})
    content = response.content.decode("utf-8")
    assert f"<mark>{TERM}</mark>" in content


def test_search_result_links_to_pages(client, user, data):
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM})
    urls = [h["url"] for h in _all_hits(response)]
    assert any(u.startswith("/vehicles/") and "tab=fuel" in u for u in urls)
    assert any(u.startswith("/vehicles/") and "tab=service" in u for u in urls)
    assert any(u.startswith("/planner/work/task/") for u in urls)


def test_search_page_anonymous_redirected(client):
    response = client.get(reverse("search:results"))
    assert response.status_code == 302
    assert "/login/" in response.url


def test_search_page_empty_query_hint(client, user):
    client.force_login(user)
    response = client.get(reverse("search:results"))
    assert "Введите запрос" in response.content.decode("utf-8")


def test_trgm_indexes_installed():
    """0001 (22) + 0002 join (4, тоже trgm_*) — суммарно 26, плюс GIN на tags."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'trgm%'")
        assert cursor.fetchone()[0] == 26
        cursor.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'gin_planner_event_tags'")
        assert cursor.fetchone() is not None


def test_pg_trgm_extension_present():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        assert cursor.fetchone() is not None


def test_search_invalid_project_uuid_no_500(client, user, data):
    """Ревью №6: не-UUID в ?project= игнорируется, а не роняет страницу."""
    client.force_login(user)
    response = client.get(reverse("search:results"), {"q": TERM, "project": "abc"})
    assert response.status_code == 200
    assert response.context["total"] > 0


def test_search_local_fields_indexed():
    """Ревью №11/№15: каждое локальное поле ilike/fts покрыто trgm-индексом 0001."""
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.search.services import ENTITIES

    m1 = import_module("apps.search.migrations.0001_trgm_search_indexes")
    covered = set(m1.TRGM_INDEXES)
    for spec in ENTITIES.values():
        model = django_apps.get_model(*spec.model.split("."))
        table = model._meta.db_table
        local = set(spec.fts_fields) | {f for f in spec.ilike_fields if "__" not in f}
        for column in local:
            assert (table, column) in covered, f"{table}.{column} без GIN trgm"


def test_search_join_fields_indexed():
    """Join-ветки (station/category/brand/model name) покрыты индексами 0002."""
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.search.services import ENTITIES, _join_target

    m2 = import_module("apps.search.migrations.0002_join_and_tags_indexes")
    covered = set(m2.TRGM_JOIN_INDEXES)
    for spec in ENTITIES.values():
        model = django_apps.get_model(*spec.model.split("."))
        for path in spec.ilike_fields:
            if "__" not in path:
                continue
            rel, field, _fk = _join_target(model, path)
            assert (rel._meta.db_table, field) in covered, f"join {path} без trgm"
