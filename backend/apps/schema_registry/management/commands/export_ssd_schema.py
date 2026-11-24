from django.core.management.base import BaseCommand

from apps.schema_registry.ssd import JSON_SCHEMA_PATH, json_schema_text


class Command(BaseCommand):
    help = "Write the SSD v1 JSON Schema to backend/schemas/ssd-v1.schema.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true", help="Fail if the committed file is out of date."
        )

    def handle(self, *args, check: bool = False, **options):
        text = json_schema_text()
        if check:
            current = JSON_SCHEMA_PATH.read_text() if JSON_SCHEMA_PATH.exists() else ""
            if current != text:
                self.stderr.write(
                    f"{JSON_SCHEMA_PATH.name} is stale. Run: python manage.py export_ssd_schema"
                )
                raise SystemExit(1)
            self.stdout.write(f"{JSON_SCHEMA_PATH.name} is up to date.")
            return
        JSON_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_SCHEMA_PATH.write_text(text, newline="\n")
        self.stdout.write(self.style.SUCCESS(f"Wrote {JSON_SCHEMA_PATH}"))
