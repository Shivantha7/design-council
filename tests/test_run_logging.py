"""Tests for run provenance helpers."""

from pathlib import Path

import pytest

from design_council.run_logging import DEFAULT_ENV_PATH, REPO_ROOT, load_env


def write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_reads_key_value_pairs(tmp_path):
    path = write_env(tmp_path, "ALPHA=one\nBETA=two\n")
    environ = {}

    loaded = load_env(path, environ)

    assert loaded == ["ALPHA", "BETA"]
    assert environ == {"ALPHA": "one", "BETA": "two"}


def test_skips_blank_lines_and_comments(tmp_path):
    path = write_env(
        tmp_path,
        "\n"
        "# a comment\n"
        "ALPHA=one\n"
        "\n"
        "   # an indented comment\n"
        "BETA=two\n"
        "\n",
    )
    environ = {}

    assert load_env(path, environ) == ["ALPHA", "BETA"]
    assert environ == {"ALPHA": "one", "BETA": "two"}


def test_does_not_override_an_existing_variable(tmp_path):
    """A value exported in the shell or set by CI wins over the file."""
    path = write_env(tmp_path, "ALPHA=from_file\nBETA=from_file\n")
    environ = {"ALPHA": "from_shell"}

    loaded = load_env(path, environ)

    assert loaded == ["BETA"]
    assert environ["ALPHA"] == "from_shell"
    assert environ["BETA"] == "from_file"


def test_strips_surrounding_quotes(tmp_path):
    path = write_env(tmp_path, "ALPHA=\"one\"\nBETA='two'\nGAMMA=three\n")
    environ = {}

    load_env(path, environ)

    assert environ == {"ALPHA": "one", "BETA": "two", "GAMMA": "three"}


def test_keeps_an_inline_hash_as_part_of_the_value(tmp_path):
    """Stripping inline comments would truncate any secret containing a '#',
    and would quietly accept a placeholder sitting in front of a real key."""
    path = write_env(tmp_path, "ALPHA=value # not-a-comment\n")
    environ = {}

    load_env(path, environ)

    assert environ["ALPHA"] == "value # not-a-comment"


def test_keeps_equals_signs_inside_the_value(tmp_path):
    path = write_env(tmp_path, "ALPHA=a=b=c\n")
    environ = {}

    load_env(path, environ)

    assert environ["ALPHA"] == "a=b=c"


def test_missing_file_is_not_an_error(tmp_path):
    """Correct when the variables come from the shell instead."""
    environ = {}

    assert load_env(tmp_path / "nonexistent.env", environ) == []
    assert environ == {}


def test_malformed_line_raises_without_quoting_the_line(tmp_path):
    """The line may be the secret, so only its number is reported."""
    path = write_env(tmp_path, "ALPHA=one\nthis-line-has-no-equals-sign\n")
    environ = {}

    with pytest.raises(ValueError) as excinfo:
        load_env(path, environ)

    message = str(excinfo.value)
    assert "line 2" in message
    assert "this-line-has-no-equals-sign" not in message


def test_empty_variable_name_raises(tmp_path):
    path = write_env(tmp_path, "=orphaned\n")

    with pytest.raises(ValueError, match="empty variable name"):
        load_env(path, {})


def test_returns_names_only_never_values(tmp_path):
    """A caller logging the return value must not be able to leak a secret."""
    path = write_env(tmp_path, "SECRET_TOKEN=sk-do-not-log-me\n")
    environ = {}

    loaded = load_env(path, environ)

    assert loaded == ["SECRET_TOKEN"]
    assert "sk-do-not-log-me" not in repr(loaded)


def test_default_path_points_at_the_repo_root(tmp_path):
    assert DEFAULT_ENV_PATH == REPO_ROOT / ".env"
    assert (REPO_ROOT / "design_council").is_dir()


def test_load_env_does_not_touch_os_environ_when_given_a_mapping(tmp_path):
    """The environ parameter exists so tests never mutate the real process."""
    import os

    path = write_env(tmp_path, "DESIGN_COUNCIL_TEST_ONLY=x\n")
    environ = {}

    load_env(path, environ)

    assert "DESIGN_COUNCIL_TEST_ONLY" in environ
    assert "DESIGN_COUNCIL_TEST_ONLY" not in os.environ
