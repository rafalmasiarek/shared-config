#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FILES_DIR = ROOT / "files"
REPOS_DIR = ROOT / "repos"
CONFIG_PATH = ROOT / "repos.yml"

IGNORED_TARGET_PATHS = {
    ".gitignore",
}


def run(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    print("+", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ""


def run_json(cmd: list[str]) -> dict:
    return json.loads(run(cmd, capture=True))


def repo_short_name(repo_name: str) -> str:
    return repo_name.split("/")[-1]


def get_repo_topics(repo_name: str) -> list[str]:
    data = run_json([
        "gh",
        "api",
        f"repos/{repo_name}/topics",
        "-H",
        "Accept: application/vnd.github+json",
    ])
    return data.get("names", [])


def safe_root_path(path: str) -> Path:
    candidate = (ROOT / path).resolve()

    if not candidate.is_relative_to(ROOT):
        raise ValueError(f"Path escapes repository root: {path}")

    return candidate


def copy_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def append_file(source: Path, destination: Path, label: str) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    existing = destination.read_text() if destination.exists() else ""
    addition = source.read_text()

    with destination.open("w") as f:
        if existing.strip():
            f.write(existing.rstrip())
            f.write("\n\n")

        f.write(f"# Added from shared-config: {label}\n")
        f.write(addition.rstrip())
        f.write("\n")


def explicit_source_paths(repo: dict) -> set[Path]:
    paths: set[Path] = set()

    for mapping in repo.get("files", []):
        source = safe_root_path(mapping["from"])
        paths.add(source)

    return paths


def copy_tree(source: Path, target: Path, skipped_sources: set[Path]) -> None:
    for item in source.rglob("*"):
        if item.is_dir():
            continue

        resolved_item = item.resolve()

        if resolved_item in skipped_sources:
            print(f"Skipping explicit file during tree copy: {item.relative_to(ROOT)}")
            continue

        relative = item.relative_to(source)
        relative_str = relative.as_posix()

        if relative_str in IGNORED_TARGET_PATHS:
            print(f"Skipping globally ignored file: {relative_str}")
            continue

        destination = target / relative
        copy_file(item, destination)


def selected_sources(repo: dict) -> list[Path]:
    repo_name = repo["name"]
    topics = get_repo_topics(repo_name)

    sources: list[Path] = []

    common_dir = FILES_DIR / "common"
    if common_dir.exists():
        sources.append(common_dir)

    for topic in topics:
        topic_dir = FILES_DIR / topic
        if topic_dir.exists():
            sources.append(topic_dir)

    dedicated_dir = REPOS_DIR / repo_short_name(repo_name)
    if dedicated_dir.exists():
        sources.append(dedicated_dir)

    return sources


def apply_sources(repo: dict, target: Path) -> None:
    skipped_sources = explicit_source_paths(repo)

    for source in selected_sources(repo):
        print(f"Applying source tree: {source.relative_to(ROOT)}")
        copy_tree(source, target, skipped_sources)


def apply_explicit_files(repo: dict, target: Path) -> None:
    for mapping in repo.get("files", []):
        source_path = mapping["from"]
        target_path = mapping["to"]
        mode = mapping.get("mode", "overwrite")

        source = safe_root_path(source_path)
        destination = target / target_path

        print(f"Applying explicit file: {source_path} -> {target_path} [{mode}]")

        if mode == "overwrite":
            copy_file(source, destination)
        elif mode == "append":
            append_file(source, destination, source_path)
        else:
            raise ValueError(f"Unsupported file mode: {mode}")


def has_changes(repo_dir: Path) -> bool:
    output = run(["git", "status", "--porcelain"], cwd=repo_dir, capture=True)
    return bool(output.strip())


def pr_exists(repo_name: str, branch: str) -> bool:
    output = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo_name,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
        ],
        capture=True,
    )
    return bool(json.loads(output))


def create_pr_if_needed(repo_name: str, branch: str, base_branch: str, defaults: dict) -> None:
    if pr_exists(repo_name, branch):
        print(f"Open PR already exists for {repo_name}:{branch}")
        return

    run([
        "gh",
        "pr",
        "create",
        "--repo",
        repo_name,
        "--base",
        base_branch,
        "--head",
        branch,
        "--title",
        defaults["pr_title"],
        "--body",
        defaults["pr_body"],
    ])


def sync_repo(repo: dict, config: dict) -> None:
    defaults = config["defaults"]

    repo_name = repo["name"]
    short_name = repo_short_name(repo_name)
    base_branch = repo.get("base_branch", defaults["base_branch"])
    branch = f"{defaults['branch_prefix']}/{short_name}"

    token = os.environ["GH_TOKEN"]
    clone_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / short_name

        run(["git", "clone", clone_url, str(repo_dir)])
        run(["git", "checkout", base_branch], cwd=repo_dir)
        run(["git", "checkout", "-B", branch], cwd=repo_dir)

        apply_sources(repo, repo_dir)
        apply_explicit_files(repo, repo_dir)

        if not has_changes(repo_dir):
            print(f"No changes for {repo_name}")
            return

        run(["git", "add", "."], cwd=repo_dir)
        run(["git", "commit", "-m", defaults["commit_message"]], cwd=repo_dir)
        run(["git", "push", "--force", "origin", branch], cwd=repo_dir)

        create_pr_if_needed(repo_name, branch, base_branch, defaults)


def main() -> None:
    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)

    for repo in config.get("repositories", []):
        sync_repo(repo, config)


if __name__ == "__main__":
    main()
