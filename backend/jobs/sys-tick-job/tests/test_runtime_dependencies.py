import importlib


def test_job_entrypoint_imports_with_installed_dependencies() -> None:
    importlib.import_module("sys_tick_job.publish_schedule_tick")
