#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
FILES_DIR = ROOT / "files"
REPOS_DIR = ROOT / "repos"
CONFIG_PATH = ROOT / "repos.yml"

IGNORED_TARGET_PATHS = {
    ".gitkeep",
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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def optional_file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    return file_sha256(path)


def merge_unique_lists(left: list[Any], right: list[Any]) -> list[Any]:
    result = list(left)
    seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in result}

    for item in right:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)

        if key not in seen:
            result.append(item)
            seen.add(key)

    return result


def merge_data(existing: Any, addition: Any) -> Any:
    if isinstance(existing, dict) and isinstance(addition, dict):
        result = dict(existing)

        for key, value in addition.items():
            if key in result:
                result[key] = merge_data(result[key], value)
            else:
                result[key] = value

        return result

    if isinstance(existing, list) and isinstance(addition, list):
        return merge_unique_lists(existing, addition)

    return addition


def copy_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def append_text_file(source: Path, destination: Path, label: str) -> None:
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


def append_yaml_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open() as f:
        addition = yaml.safe_load(f) or {}

    if destination.exists() and destination.read_text().strip():
        with destination.open() as f:
            existing = yaml.safe_load(f) or {}
    else:
        existing = {}

    merged = merge_data(existing, addition)

    with destination.open("w") as f:
        yaml.safe_dump(
            merged,
            f,
            sort_keys=False,
            allow_unicode=True,
        )


def append_json_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open() as f:
        addition = json.load(f)

    if destination.exists() and destination.read_text().strip():
        with destination.open() as f:
            existing = json.load(f)
    else:
        existing = {}

    merged = merge_data(existing, addition)

    with destination.open("w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_file(source: Path, destination: Path, label: str) -> str:
    suffix = source.suffix.lower()

    if suffix in {".yml", ".yaml"}:
        append_yaml_file(source, destination)
        return "append-yaml"

    if suffix == ".json":
        append_json_file(source, destination)
        return "append-json"

    append_text_file(source, destination, label)
    return "append-text"


def resolve_file_mode(source_path: str, mapping: dict | None, config: dict) -> str:
    if mapping and "mode" in mapping:
        return mapping["mode"]

    return config.get("policies", {}).get(source_path, {}).get("mode", "overwrite")


def apply_file(
    source: Path,
    destination: Path,
    source_path: str,
    target_path: str,
    mode: str,
    report: list[dict],
) -> None:
    before_hash = optional_file_sha256(destination)

    print(f"Applying file: {source_path} -> {target_path} [{mode}]")

    if mode == "overwrite":
        copy_file(source, destination)
        final_mode = "overwrite"
    elif mode == "append":
        final_mode = append_file(source, destination, source_path)
    else:
        raise ValueError(f"Unsupported file mode: {mode}")

    after_hash = optional_file_sha256(destination)

    if before_hash is None:
        status = "added"
    elif before_hash == after_hash:
        status = "unchanged"
    else:
        status = "modified"

    stat = source.stat()

    report.append({
        "source": source_path,
        "target": target_path,
        "mode": final_mode,
        "status": status,
        "size": stat.st_size,
        "sha256": file_sha256(source),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    })


def explicit_source_paths(repo: dict) -> set[Path]:
    paths: set[Path] = set()

    for mapping in repo.get("files", []):
        source = safe_root_path(mapping["from"])
        paths.add(source)

    return paths


def copy_tree(
    source: Path,
    target: Path,
    skipped_sources: set[Path],
    excluded_paths: set[str],
    config: dict,
    report: list[dict],
) -> None:
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

        if relative_str in excluded_paths:
            print(f"Skipping repo excluded file: {relative_str}")
            continue

        source_path = item.relative_to(ROOT).as_posix()
        target_path = relative_str
        destination = target / relative
        mode = resolve_file_mode(source_path, None, config)

        apply_file(
            item,
            destination,
            source_path,
            target_path,
            mode,
            report,
        )


def selected_sources(repo: dict) -> list[Path]:
    repo_name = repo["name"]
    topics = get_repo_topics(repo_name)

    print(f"Repository topics for {repo_name}: {topics}")

    sources: list[Path] = []

    common_dir = FILES_DIR / "common"
    if common_dir.exists():
        print(f"Matched common directory: {common_dir.relative_to(ROOT)}")
        sources.append(common_dir)

    for topic in topics:
        topic_dir = FILES_DIR / topic

        if topic_dir.exists():
            print(f"Matched topic directory: {topic_dir.relative_to(ROOT)}")
            sources.append(topic_dir)
        else:
            print(f"No local directory for topic: {topic}")

    dedicated_dir = REPOS_DIR / repo_short_name(repo_name)
    if dedicated_dir.exists():
        print(f"Matched dedicated directory: {dedicated_dir.relative_to(ROOT)}")
        sources.append(dedicated_dir)

    return sources


def apply_sources(repo: dict, target: Path, config: dict, report: list[dict]) -> None:
    skipped_sources = explicit_source_paths(repo)
    excluded_paths = set(repo.get("exclude", []))

    for source in selected_sources(repo):
        print(f"Applying source tree: {source.relative_to(ROOT)}")
        copy_tree(source, target, skipped_sources, excluded_paths, config, report)


def apply_explicit_files(repo: dict, target: Path, config: dict, report: list[dict]) -> None:
    for mapping in repo.get("files", []):
        source_path = mapping["from"]
        target_path = mapping["to"]

        source = safe_root_path(source_path)
        destination = target / target_path
        mode = resolve_file_mode(source_path, mapping, config)

        apply_file(
            source,
            destination,
            source_path,
            target_path,
            mode,
            report,
        )


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


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|")


def render_sync_report(report: list[dict]) -> str:
    if not report:
        return ""

    lines = [
        "",
        "## Sync report",
        "",
        "| Source | Target | Mode | Status | Size | SHA256 | Modified |",
        "|---|---|---|---|---:|---|---|",
    ]

    for row in report:
        short_hash = row["sha256"][:12]
        lines.append(
            "| "
            f"`{markdown_escape(row['source'])}` | "
            f"`{markdown_escape(row['target'])}` | "
            f"`{markdown_escape(row['mode'])}` | "
            f"`{markdown_escape(row['status'])}` | "
            f"{row['size']} B | "
            f"`{short_hash}` | "
            f"{markdown_escape(row['modified'])} |"
        )

    return "\n".join(lines)


def create_pr_if_needed(
    repo_name: str,
    branch: str,
    base_branch: str,
    defaults: dict,
    report: list[dict],
) -> None:
    if pr_exists(repo_name, branch):
        print(f"Open PR already exists for {repo_name}:{branch}")
        return

    body = defaults["pr_body"].rstrip()
    body += "\n"
    body += render_sync_report(report)

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
        body,
    ])


def sync_repo(repo: dict, config: dict) -> None:
    defaults = config["defaults"]

    repo_name = repo["name"]
    short_name = repo_short_name(repo_name)
    base_branch = repo.get("base_branch", defaults["base_branch"])
    branch = f"{defaults['branch_prefix']}/{short_name}"
    report: list[dict] = []

    token = os.environ["GH_TOKEN"]
    clone_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / short_name

        run(["git", "clone", clone_url, str(repo_dir)])
        run(["git", "checkout", base_branch], cwd=repo_dir)
        run(["git", "checkout", "-B", branch], cwd=repo_dir)

        apply_sources(repo, repo_dir, config, report)
        apply_explicit_files(repo, repo_dir, config, report)

        if not has_changes(repo_dir):
            print(f"No changes for {repo_name}")
            return

        run(["git", "add", "."], cwd=repo_dir)
        run(["git", "commit", "-m", defaults["commit_message"]], cwd=repo_dir)
        run(["git", "push", "--force", "origin", branch], cwd=repo_dir)

        create_pr_if_needed(repo_name, branch, base_branch, defaults, report)


def main() -> None:
    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)

    for repo in config.get("repositories", []):
        sync_repo(repo, config)


if __name__ == "__main__":
    main()