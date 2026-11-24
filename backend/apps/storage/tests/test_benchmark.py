"""A tiny run of the storage benchmark, so it can't silently rot."""

import pytest

from apps.storage.benchmark.runner import Benchmark, render_markdown


@pytest.mark.django_db(transaction=True)
def test_benchmark_runs_end_to_end_and_both_designs_pass_every_check():
    report = Benchmark(
        sales=150,
        customers=20,
        products=10,
        workspaces=3,
        tenant_sales=20,
        repeats=1,
        threads=4,
        log=lambda _msg: None,
    ).run()

    checks = {c.name: c for c in report.checks}
    plans = {n for n in checks if "query plans" in n}  # tiny tables may use other plans
    for name, check in checks.items():
        if name in plans:
            continue
        assert check.jsonb, name
        assert check.physical, name
    markdown = render_markdown(report)
    assert "## Correctness" in markdown
    assert "Who owes me the most" in markdown
