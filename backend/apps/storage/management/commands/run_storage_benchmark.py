"""Run the JSONB vs physical-tables storage benchmark (spec section 9, Phase 2 exit gate).

    python manage.py run_storage_benchmark                 # full run, a few minutes
    python manage.py run_storage_benchmark --quick         # small sizes, under a minute

It creates a throwaway test database (like pytest does), runs every scenario, writes the
Markdown report, and drops the database again. Your development data is never touched.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test.utils import setup_databases, teardown_databases

from apps.storage.benchmark.runner import Benchmark, render_markdown

DEFAULT_OUTPUT = Path(settings.BASE_DIR).parent / "docs" / "benchmarks" / "storage-benchmark.md"


class Command(BaseCommand):
    help = "Benchmark JSONB records against physical per-workspace tables."

    def add_arguments(self, parser):
        parser.add_argument("--quick", action="store_true", help="Small sizes for a smoke run.")
        parser.add_argument("--sales", type=int, default=10_000)
        parser.add_argument("--workspaces", type=int, default=100)
        parser.add_argument("--tenant-sales", type=int, default=500)
        parser.add_argument("--repeats", type=int, default=20)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    def handle(self, *args, **options):
        sizes = {
            "sales": options["sales"],
            "workspaces": options["workspaces"],
            "tenant_sales": options["tenant_sales"],
            "repeats": options["repeats"],
        }
        if options["quick"]:
            sizes = {"sales": 1000, "workspaces": 10, "tenant_sales": 100, "repeats": 5}

        self.stdout.write("Creating a throwaway benchmark database...")
        old_config = setup_databases(verbosity=0, interactive=False)
        try:
            report = Benchmark(**sizes, log=self.stdout.write).run()
        finally:
            teardown_databases(old_config, verbosity=0)

        output: Path = options["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report) + "\n", encoding="utf-8")
        failed = [c.name for c in report.checks if not c.jsonb or not c.physical]
        self.stdout.write(self.style.SUCCESS(f"Report written to {output}"))
        if failed:
            self.stdout.write(f"Checks failed in at least one design: {failed}")
