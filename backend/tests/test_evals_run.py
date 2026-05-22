import textwrap

import pytest

from evals.providers import ModelSpec
from evals.run import RunConfigError, load_run_config


def _write(tmp_path, body: str):
    path = tmp_path / "run.toml"
    path.write_text(textwrap.dedent(body))
    return path


def test_load_minimal_ai_run(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "demo"

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "ep-1"
        """,
    )
    config = load_run_config(path)
    assert config.name == "demo"
    assert config.iou_threshold == 0.5
    assert config.use_acast_default is False
    assert config.models == [ModelSpec(provider="gemini", model="gemini-2.5-flash")]
    assert len(config.cases) == 1
    assert config.cases[0].id == "ep-1"
    assert config.cases[0].use_acast is False


def test_load_inherits_use_acast_default(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "acast-run"
        use_acast = true

        [[cases]]
        id = "ep-acast"
        """,
    )
    config = load_run_config(path)
    assert config.use_acast_default is True
    assert config.cases[0].use_acast is True
    assert config.models == []  # acast-only is allowed without models


def test_load_per_case_override(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "mixed"
        use_acast = false

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "ai-case"

        [[cases]]
        id = "acast-case"
        use_acast = true
        """,
    )
    config = load_run_config(path)
    assert [c.use_acast for c in config.cases] == [False, True]


def test_load_supports_provider_model_form(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "split-model-spec"

        [[models]]
        provider = "gemini"
        model = "gemini-2.5-flash-lite"

        [[cases]]
        id = "ep-1"
        """,
    )
    config = load_run_config(path)
    assert config.models == [ModelSpec(provider="gemini", model="gemini-2.5-flash-lite")]


def test_load_rejects_unknown_top_level_key(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "demo"
        wat = "nope"

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "ep-1"
        """,
    )
    with pytest.raises(RunConfigError, match="Unknown"):
        load_run_config(path)


def test_load_rejects_unknown_case_key(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "demo"

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "ep-1"
        garbage = true
        """,
    )
    with pytest.raises(RunConfigError, match="Unknown"):
        load_run_config(path)


def test_load_requires_models_when_any_ai_case(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "no-models"

        [[cases]]
        id = "ai-case"
        """,
    )
    with pytest.raises(RunConfigError, match="no \\[\\[models\\]\\]"):
        load_run_config(path)


def test_load_requires_cases(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "no-cases"

        [[models]]
        spec = "gemini:gemini-2.5-flash"
        """,
    )
    with pytest.raises(RunConfigError, match="no \\[\\[cases\\]\\]"):
        load_run_config(path)


def test_load_case_id_required(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "demo"

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        podcast = "Some Podcast"
        """,
    )
    with pytest.raises(RunConfigError, match="missing required 'id'"):
        load_run_config(path)


def test_load_missing_file_errors():
    with pytest.raises(RunConfigError, match="not found"):
        load_run_config("/tmp/does-not-exist-42.toml")


def test_per_case_iou_override(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = "iou-override"
        iou_threshold = 0.5

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "tight"
        iou_threshold = 0.75

        [[cases]]
        id = "loose"
        """,
    )
    config = load_run_config(path)
    assert config.iou_threshold == 0.5
    assert config.cases[0].iou_threshold == 0.75
    assert config.cases[1].iou_threshold is None


def test_load_rejects_bad_type(tmp_path):
    path = _write(
        tmp_path,
        """
        [run]
        name = 42

        [[models]]
        spec = "gemini:gemini-2.5-flash"

        [[cases]]
        id = "ep-1"
        """,
    )
    with pytest.raises(RunConfigError, match="must be a string"):
        load_run_config(path)
