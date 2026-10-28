import subprocess
from dataclasses import replace

import pytest


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

from knowitall_publication import PublicationValidationError, authoritative_deletions
from knowitall_snapshot import SnapshotPolicy, create_snapshot


def snapshots_across_changes(make_repo, tmp_path):
    repo = make_repo()
    root = tmp_path / "snapshots"
    policy = SnapshotPolicy()
    first = create_snapshot(repo, "project", "repo", root, policy)
    (repo / "src" / "orders.py").write_text("def changed():\n    return True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "modify")
    modified = create_snapshot(repo, "project", "repo", root, policy)
    git(repo, "mv", "src/store.py", "src/persistence.py")
    git(repo, "commit", "-qm", "rename")
    renamed = create_snapshot(repo, "project", "repo", root, policy)
    git(repo, "rm", "src/persistence.py")
    git(repo, "commit", "-qm", "delete")
    deleted = create_snapshot(repo, "project", "repo", root, policy)
    return first, modified, renamed, deleted


def test_modified_renamed_deleted_commits_get_new_snapshot_identities(make_repo, tmp_path):
    snapshots = snapshots_across_changes(make_repo, tmp_path)

    assert len({snapshot.snapshot_id for snapshot in snapshots}) == 4
    assert len({snapshot.commit for snapshot in snapshots}) == 4
    assert {entry.path for entry in snapshots[2].included} == {"src/orders.py", "src/persistence.py"}
    assert {entry.path for entry in snapshots[3].included} == {"src/orders.py"}


def test_complete_inventory_authorizes_deleted_and_renamed_paths(make_repo, tmp_path):
    first, _, renamed, deleted = snapshots_across_changes(make_repo, tmp_path)

    assert authoritative_deletions(first, renamed) == {"src/store.py"}
    assert authoritative_deletions(renamed, deleted) == {"src/persistence.py"}


def test_incomplete_inventory_never_implies_deletion(make_repo, tmp_path):
    first, _, renamed, _ = snapshots_across_changes(make_repo, tmp_path)
    incomplete = replace(renamed, inventory_complete=False, failed=({"path": ".", "reason": "listing_failed"},))

    with pytest.raises(PublicationValidationError, match="deletion authority"):
        authoritative_deletions(first, incomplete)


def test_authoritative_git_delta_must_bind_both_revisions(make_repo, tmp_path):
    first, _, renamed, _ = snapshots_across_changes(make_repo, tmp_path)
    incomplete = replace(renamed, inventory_complete=False)

    assert authoritative_deletions(first, incomplete, git_delta={"from": first.commit, "to": renamed.commit, "deleted": ["src/store.py"]}) == {"src/store.py"}
    with pytest.raises(PublicationValidationError, match="revision"):
        authoritative_deletions(first, incomplete, git_delta={"from": "wrong", "to": renamed.commit, "deleted": ["src/store.py"]})


def test_parser_failure_is_partial_and_not_deletion(generation_factory):
    generation, _ = generation_factory()
    partial = replace(generation, state="partial", coverage=replace(generation.coverage, extraction="partial", relevant_scope="partial", limitations=("parser_error",)), failed_files=((generation.nodes[-1].path, "parser_error"),))

    assert partial.nodes[-1].path in {node.path for node in partial.nodes}
    assert partial.failed_files
