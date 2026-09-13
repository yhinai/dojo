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


def test_registry_semantics_are_diverse_and_contracts_public():
    from herd.task_registry import CONTRACTS

    registry = TaskRegistry("runtime", "docs")
    tasks = [registry.generate(Partition.CALIBRATION, i) for i in range(12)]
    assert len(set(CONTRACTS.values())) >= 10
    sources = [registry.reference_source(task) for task in tasks]
    assert any("mo.state(" in source for source in sources)
    assert any("mo.stop(" in source for source in sources)
    assert any("mo.ui.table(" in source for source in sources)
    assert any("include_negative" in source for source in sources)
    assert any("offset.value" in source for source in sources)
    assert all(task.public_fixture["interaction_contract"] in task.public_skill_tags for task in tasks)
    forward = sources[2]
    assert forward.index("def transform") < forward.index("def data")


def test_independent_dependencies_have_discriminating_private_cases():
    registry = TaskRegistry("runtime", "docs")
    for partition in (Partition.CALIBRATION, Partition.ADMISSION, Partition.FINAL):
        for seed in (4, 5, 6, 10, 11):
            task = registry.generate(partition, seed)
            probes = registry.private_probes(task)
            assert any(
                registry.expected_result(task, probe)
                != registry.expected(task, probe["records"], probe["value"])
                for probe in probes
            ), task.family_id


def test_references_fit_output_budget_proxy():
    """cl100k is an explicit planning proxy, not a guarantee for the chosen provider tokenizer."""
    import json

    import tiktoken

    registry = TaskRegistry("runtime", "docs")
    encoding = tiktoken.get_encoding("cl100k_base")
    for partition in (Partition.DEVELOPMENT, Partition.FINAL):
        for seed in range(60):
            task = registry.generate(partition, seed)
            submission = json.dumps({"action": "submit", "source": registry.reference_source(task)})
            assert len(encoding.encode(submission)) < task.budget.max_output_tokens_per_turn


def test_public_structural_contracts_reject_generic_template_but_allow_alternatives():
    registry = TaskRegistry("runtime", "docs")
    generic = registry.reference_source(registry.generate(Partition.CALIBRATION, 3))
    for seed in (0, 1, 2):
        task = registry.generate(Partition.CALIBRATION, seed)
        assert not all(passed for _, passed in registry.structure_requirements(task, generic))
        alternative = registry.reference_source(task).replace("def transform(", "def analysis(")
        alternative = (
            alternative.replace("_preview", "_temporary")
            if seed != 1
            else alternative.replace("    _preview =", "    _rows =").replace("= _preview", "= _rows")
        )
        assert all(passed for _, passed in registry.structure_requirements(task, alternative))
