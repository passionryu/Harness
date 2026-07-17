import subprocess


def test_legacy_python_execution_layer_is_removed_from_git():
    completed = subprocess.run(
        ["git", "ls-files", "agents/runners"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == ""
