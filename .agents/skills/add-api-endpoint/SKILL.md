---
name: add-api-endpoint
description: Add or change a REST API endpoint end to end in this Django/DRF template. Covers the model on django_core BaseModel, the migration, the serializer, a generic view with explicit permission_classes, the URL under api/v1/, the admin, a factory, tests and a Swagger check. Use when asked to add an endpoint, API, resource or CRUD, or a new Django app.
---
# Add an API endpoint

Read AGENTS.md first (Conventions, Security rules). Run every command from the repo root with the `.venv/bin/` paths.

1. New app only: create `<app>/__init__.py` (without it Python imports the app as a namespace package and `manage.py test` silently skips its tests), `<app>/apps.py`, and the `models/`, `serializers/`, `views/`, `admin/`, `factories/`, `tests/` and `migrations/` packages, each with `__init__.py`, mirroring `authentication/`. Don't use `startapp`: it creates flat files. In `<app>/apps.py` set `default_auto_field = "django.db.models.BigAutoField"`. Append the app to INSTALLED_APPS in `django_template/settings/base.py`, and add `path("api/v1/<app>/", include("<app>.urls"))` to `django_template/urls.py`.
2. Model in `models/<thing>.py`, subclassing `django_core.models.BaseModel`. An owner foreign key points at `settings.AUTH_USER_MODEL`. Export it explicitly from `models/__init__.py`.
3. `.venv/bin/python manage.py makemigrations <app> --name add_<thing>`, then `.venv/bin/black <app>/migrations/<NNNN>_add_<thing>.py` (Django formats new migrations itself only when `black` is on PATH, and the venv isn't activated). Review it against `.claude/rules/migrations.md` and `.venv/bin/python manage.py sqlmigrate <app> <NNNN>`.
4. `serializers/<thing>_serializer.py` with explicit `fields`. `owner`, `created_at` and `updated_at` are read-only.
5. `views/<thing>_view.py`: a `generics.*` view with `permission_classes = (IsAuthenticated,)`, `get_queryset()` filtered by `self.request.user` (start it with `if getattr(self, "swagger_fake_view", False): return <Model>.objects.none()`: drf-yasg builds /swagger.json with an anonymous user, and without this every schema request logs a TypeError traceback), and `perform_create()` setting the owner. Pagination: create `django_core/pagination.py` once (a PageNumberPagination subclass with `page_size = 20`, `page_size_query_param = "page_size"` and `max_page_size = 100`; `max_page_size` only applies when `page_size_query_param` is set) and set `pagination_class` on the view. Add `filterset_fields`.
6. `<app>/urls.py`: name every route.
7. Admin: add `(Model, ModelAdmin)` to `register_list` in `<app>/admin/__init__.py`.
8. Factory: use `factory.Sequence` or `factory.Faker` for unique fields and `password = factory.django.Password("pw")`. Never call `fake.x()` at class level, as `CustomerFactory` does.
9. Tests in `<app>/tests/test_<thing>_views.py` as `rest_framework.test.APITestCase`, using `reverse("<route name>")` and `self.client.force_authenticate(user)`. Cover: no auth returns 401, another user's object returns 404, and the happy path for list and create. Once per project, add a test that `GET /swagger.json` returns 200.
10. Verify: `.venv/bin/python manage.py test --noinput <app>` (check the "Found N test(s)" count went up), `.venv/bin/python manage.py makemigrations --check --dry-run`, then `.venv/bin/flake8`, `.venv/bin/black --check` and `.venv/bin/isort --check-only` on the changed files.
