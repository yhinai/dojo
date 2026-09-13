from herd.schemas import Partition
from herd.task_registry import TaskRegistry


def test_registry_has_twelve_families_and_five_tracks():
    registry = TaskRegistry("runtime", "docs")
    tasks = [registry.generate(Partition.FINAL, i) for i in range(60)]
    assert len({task.family_id for task in tasks}) == 12
    assert {task.track for task in tasks} == set(range(5))
    assert len({task.task_id for task in tasks}) == 60
    assert all("expected" not in task.model_dump_json() for task in tasks)


def test_registry_determinism_and_partition_separation():
    registry = TaskRegistry("runtime", "docs")
    assert registry.generate(Partition.DEVELOPMENT, 5) == registry.generate(Partition.DEVELOPMENT, 5)
    development = registry.generate(Partition.DEVELOPMENT, 5)
    final = registry.generate(Partition.FINAL, 5)
    assert development.task_id != final.task_id
    assert development.public_fixture != final.public_fixture


def test_oracle_boundary_semantics():
    registry = TaskRegistry("runtime", "docs")
    rows = [{"category": "A", "amount": 2}, {"category": "A", "amount": 2}, {"category": "B", "amount": -2}]
    inclusive = registry.generate(Partition.CALIBRATION, 3)
    exclusive = registry.generate(Partition.CALIBRATION, 4)
    assert registry.expected(inclusive, rows, 2) == 4
    assert registry.expected(exclusive, rows, 2) == 0
