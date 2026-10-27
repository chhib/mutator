from pathlib import Path

from mutator import runner
from mutator.sites import apply_site, discover_raw

MODEL = """{{ config(materialized='table') }}
with live as (
    select * from {{ ref('raw') }} where deleted_at is null and amount >= 0
)
select * from live
"""


def test_sql_sites_skip_jinja_and_apply_cleanly():
    found = discover_raw(MODEL, "sql", "models/live.sql")
    assert [(site.line, site.original, site.mutant) for site in found] == [
        (3, "is", "is not"),
        (3, "and", "or"),
        (3, ">=", ">"),
        (3, "0", "1"),
    ]
    mutated = apply_site(MODEL, found[0].start, found[0].end, found[0].mutant)
    assert "where deleted_at is not null" in mutated
    assert mutated.startswith("{{ config(materialized='table') }}")


def _project(tmp_path: Path) -> Path:
    (tmp_path / "profiles.yml").write_text("demo: {}\n")
    project = tmp_path / "demo"
    (project / "models").mkdir(parents=True)
    (project / "macros").mkdir()
    (project / "dbt_project.yml").write_text("name: demo\n")
    return project


def test_a_model_runs_its_own_unit_tests(tmp_path):
    project = _project(tmp_path)
    command, cwd = runner.test_plan(tmp_path, project / "models" / "live.sql", "sql", None)
    assert cwd == project.resolve()
    assert command == [
        "dbt", "test", "--select", "live,test_type:unit", "--profiles-dir", str(tmp_path.resolve()),
    ]


def test_a_macro_runs_every_unit_test(tmp_path):
    project = _project(tmp_path)
    command, _cwd = runner.test_plan(tmp_path, project / "macros" / "m.sql", "sql", None)
    assert command[3] == "test_type:unit"


def test_a_dbt_worker_is_a_real_copy_with_linked_packages(tmp_path):
    from mutator.workers import create_workers

    root = tmp_path / "repo"
    root.mkdir()
    project = _project(root)
    (project / "models" / "live.sql").write_text("select 1")
    (project / "models" / "other.sql").write_text("select 2")
    (project / "dbt_packages" / "dbt_utils").mkdir(parents=True)
    (project / "target").mkdir()
    (project / "logs").mkdir()
    relative = "demo/models/live.sql"
    [worker] = create_workers(tmp_path / "run", root, relative, b"select 1", 1)
    copy = worker / "demo"
    assert not copy.is_symlink() and not (copy / "dbt_project.yml").is_symlink()
    assert not (copy / "models").is_symlink() and not (copy / "models" / "other.sql").is_symlink()
    assert (copy / "dbt_packages").is_symlink()
    assert not (copy / "target").exists()
    assert (copy / "logs").is_dir() and not (copy / "logs").is_symlink()
    assert (copy / "models" / "live.sql").read_text() == "select 1"
