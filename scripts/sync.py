#!/usr/bin/env python3

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
FILES_DIR = ROOT / "files"
REPOS_DIR = ROOT / "repos"
CONFIG_PATH = ROOT / "repos.yml"

IGNORED_TARGET_PATHS = {
    ".gitkeep",
}
SHARED_BLOCK_MARKER_RE = re.compile(
    r"(?m)^[ \t]*# shared-config:block:(?P<action>start|end): "
    r"(?P<name>[A-Za-z0-9_.-]+)[ \t]*(?:\r?\n|$)"
)


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


def run_json(cmd: list[str]) -> Any:
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


def render_template(content: str, context: dict[str, Any]) -> str:
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )

    template = env.from_string(content)
    return template.render(**context)


def read_source_text(source: Path, context: dict[str, Any]) -> str:
    content = source.read_text()

    if source.suffix == ".tpl":
        return render_template(content, context)

    return content


def target_relative_path(relative: Path) -> Path:
    if relative.suffix == ".tpl":
        return relative.with_suffix("")

    return relative


def target_path_from_mapping(target_path: str) -> str:
    if target_path.endswith(".tpl"):
        return target_path[:-4]

    return target_path


def source_report_path(source: Path) -> str:
    return source.relative_to(ROOT).as_posix()


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


def write_rendered_file(source: Path, destination: Path, context: dict[str, Any]) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(read_source_text(source, context))


def copy_file(source: Path, destination: Path, context: dict[str, Any]) -> None:
    if source.suffix == ".tpl":
        write_rendered_file(source, destination, context)
        return

    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def append_text_file(source: Path, destination: Path, label: str, context: dict[str, Any]) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    existing = destination.read_text() if destination.exists() else ""
    addition = read_source_text(source, context)

    with destination.open("w") as f:
        if existing.strip():
            f.write(existing.rstrip())
            f.write("\n\n")

        f.write(f"# Added from shared-config: {label}\n")
        f.write(addition.rstrip())
        f.write("\n")

def append_yaml_file(source: Path, destination: Path, context: dict[str, Any]) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    existing = destination.read_text() if destination.exists() else ""
    addition = read_source_text(source, context)

    if existing.strip():
        merged_text = existing.rstrip() + "\n" + addition.rstrip() + "\n"
    else:
        merged_text = addition.rstrip() + "\n"

    # Validate final YAML, but keep the original formatting and comments.
    yaml.safe_load(merged_text)

    destination.write_text(merged_text)

def append_json_file(source: Path, destination: Path, context: dict[str, Any]) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise ValueError(f"Source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    addition = json.loads(read_source_text(source, context))

    if destination.exists() and destination.read_text().strip():
        with destination.open() as f:
            existing = json.load(f)
    else:
        existing = {}

    merged = merge_data(existing, addition)

    with destination.open("w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_file(source: Path, destination: Path, label: str, context: dict[str, Any]) -> str:
    suffix = destination.suffix.lower()

    if suffix in {".yml", ".yaml"}:
        append_yaml_file(source, destination, context)
        return "append-yaml"

    if suffix == ".json":
        append_json_file(source, destination, context)
        return "append-json"

    append_text_file(source, destination, label, context)
    return "append-text"


def resolve_file_mode(source_path: str, mapping: dict | None, config: dict) -> str:
    if mapping and "mode" in mapping:
        return mapping["mode"]

    return config.get("policies", {}).get(source_path, {}).get("mode", "overwrite")


def resolve_commit_message(repo: dict, defaults: dict) -> str:
    return repo.get("commit_message", defaults.get("commit_message", "chore: sync shared config"))


def build_template_context(
    repo: dict,
    repo_name: str,
    short_name: str,
    topics: list[str],
    source_path: str,
    target_path: str,
    base_branch: str,
    branch: str,
    config: dict,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "repo": repo_name,
        "repo_short_name": short_name,
        "topics": topics,
        "topics_csv": ",".join(topics),
        "source": source_path,
        "target": target_path,
        "base_branch": base_branch,
        "sync_branch": branch,
    }

    context.update(config.get("vars", {}))

    for topic in topics:
        context.update(config.get("topic_vars", {}).get(topic, {}))

    context.update(repo.get("vars", {}))
    context.update(config.get("file_vars", {}).get(source_path, {}))

    return context


def apply_file(
    source: Path,
    destination: Path,
    source_path: str,
    target_path: str,
    mode: str,
    context: dict[str, Any],
    report: list[dict],
    excluded_blocks: list[dict],
) -> None:
    matching_rules = [rule for rule in excluded_blocks if rule["path"] == target_path]
    source_content = (
        read_source_text(source, context)
        if source.suffix == ".tpl" or matching_rules
        else None
    )

    if source_content is not None and not source_content.strip():
        print(f"Skipping empty rendered template: {target_path}")
        stat = source.stat()
        report.append({
            "source": source_path,
            "target": target_path,
            "mode": "empty-template",
            "status": "skipped",
            "size": stat.st_size,
            "sha256": file_sha256(source),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
        return

    if matching_rules:
        if mode != "overwrite":
            raise ValueError(f"Block exclusions require overwrite mode: {target_path}")
        if not destination.is_file():
            raise ValueError(
                f"Cannot preserve excluded blocks because destination file is missing: {target_path}"
            )

        source_content = preserve_excluded_blocks(
            source_content,
            destination.read_text(),
            [rule["name"] for rule in matching_rules],
            target_path,
        )

    before_hash = optional_file_sha256(destination)

    print(f"Applying file: {source_path} -> {target_path} [{mode}]")

    if mode == "overwrite":
        if source_content is None:
            copy_file(source, destination, context)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source_content)
        final_mode = "overwrite-template" if source.suffix == ".tpl" else "overwrite"
    elif mode == "append":
        final_mode = append_file(source, destination, source_path, context)
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


def is_excluded_path(target_path: str, excluded_paths: set[str]) -> bool:
    return target_path in excluded_paths


def validate_excluded_blocks(config: dict) -> None:
    for repo in config.get("repositories", []):
        for rule in repo.get("exclude_blocks", []):
            if not isinstance(rule, dict):
                raise ValueError(f"Invalid block exclusion for {repo.get('name')}: expected an object")

            path = rule.get("path")
            name = rule.get("name")

            if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError(f"Invalid block exclusion path for {repo.get('name')}: {path}")

            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise ValueError(f"Invalid block exclusion name for {repo.get('name')}: {name}")


def named_blocks(content: str, path: str) -> dict[str, tuple[int, int]]:
    blocks: dict[str, tuple[int, int]] = {}
    open_block: tuple[str, int] | None = None

    for marker in SHARED_BLOCK_MARKER_RE.finditer(content):
        action = marker.group("action")
        name = marker.group("name")

        if action == "start":
            if open_block or name in blocks:
                raise ValueError(f"Nested or duplicate shared-config block '{name}' in {path}")
            open_block = (name, marker.start())
        else:
            if not open_block or open_block[0] != name:
                raise ValueError(f"Unmatched shared-config block end '{name}' in {path}")
            blocks[name] = (open_block[1], marker.end())
            open_block = None

    if open_block:
        raise ValueError(f"Unclosed shared-config block '{open_block[0]}' in {path}")

    return blocks


def preserve_excluded_blocks(
    source_content: str,
    destination_content: str,
    excluded_names: list[str],
    target_path: str,
) -> str:
    source_blocks = named_blocks(source_content, target_path)
    destination_blocks = named_blocks(destination_content, target_path)
    replacements: list[tuple[int, int, str]] = []

    for name in excluded_names:
        if name not in source_blocks or name not in destination_blocks:
            raise ValueError(
                f"Cannot preserve shared-config block '{name}' in {target_path}; "
                "the block must be marked in both source and destination"
            )

        start, end = source_blocks[name]
        old_start, old_end = destination_blocks[name]
        replacements.append((start, end, destination_content[old_start:old_end]))
        print(f"Preserving existing block '{name}' in {target_path}")

    for start, end, existing_block in sorted(replacements, reverse=True):
        source_content = source_content[:start] + existing_block + source_content[end:]

    return source_content


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
    repo: dict,
    repo_name: str,
    short_name: str,
    topics: list[str],
    base_branch: str,
    branch: str,
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
        target_relative = target_relative_path(relative)
        target_path = target_relative.as_posix()

        if relative_str in IGNORED_TARGET_PATHS:
            print(f"Skipping globally ignored file: {relative_str}")
            continue

        if is_excluded_path(target_path, excluded_paths) or relative_str in excluded_paths:
            print(f"Skipping repo excluded file: {target_path}")
            continue

        source_path = source_report_path(item)
        destination = target / target_relative
        mode = resolve_file_mode(source_path, None, config)

        context = build_template_context(
            repo,
            repo_name,
            short_name,
            topics,
            source_path,
            target_path,
            base_branch,
            branch,
            config,
        )

        apply_file(
            item,
            destination,
            source_path,
            target_path,
            mode,
            context,
            report,
            repo.get("exclude_blocks", []),
        )


def selected_sources(repo: dict, topics: list[str]) -> list[Path]:
    repo_name = repo["name"]

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


def apply_sources(
    repo: dict,
    target: Path,
    repo_name: str,
    short_name: str,
    topics: list[str],
    base_branch: str,
    branch: str,
    config: dict,
    report: list[dict],
) -> None:
    skipped_sources = explicit_source_paths(repo)
    excluded_paths = set(repo.get("exclude", []))

    for source in selected_sources(repo, topics):
        print(f"Applying source tree: {source.relative_to(ROOT)}")
        copy_tree(
            source,
            target,
            skipped_sources,
            excluded_paths,
            repo,
            repo_name,
            short_name,
            topics,
            base_branch,
            branch,
            config,
            report,
        )


def apply_explicit_files(
    repo: dict,
    target: Path,
    repo_name: str,
    short_name: str,
    topics: list[str],
    base_branch: str,
    branch: str,
    config: dict,
    report: list[dict],
) -> None:
    excluded_paths = set(repo.get("exclude", []))

    for mapping in repo.get("files", []):
        source_path = mapping["from"]
        target_path = target_path_from_mapping(mapping["to"])

        if is_excluded_path(target_path, excluded_paths):
            print(f"Skipping repo excluded file: {target_path}")
            continue

        source = safe_root_path(source_path)
        destination = target / target_path
        mode = resolve_file_mode(source_path, mapping, config)

        context = build_template_context(
            repo,
            repo_name,
            short_name,
            topics,
            source_path,
            target_path,
            base_branch,
            branch,
            config,
        )

        apply_file(
            source,
            destination,
            source_path,
            target_path,
            mode,
            context,
            report,
            repo.get("exclude_blocks", []),
        )


def has_changes(repo_dir: Path) -> bool:
    output = run(["git", "status", "--porcelain"], cwd=repo_dir, capture=True)
    return bool(output.strip())


def get_merged_renovate_pr() -> dict | None:
    repository = os.environ.get("GITHUB_REPOSITORY")
    commit = os.environ.get("GITHUB_SHA")

    if not repository or not commit:
        return None

    pull_requests = run_json([
        "gh",
        "api",
        f"repos/{repository}/commits/{commit}/pulls",
    ])

    if not isinstance(pull_requests, list):
        raise ValueError("GitHub returned an invalid pull request list for the sync commit")

    renovate_prs = [
        pull_request
        for pull_request in pull_requests
        if isinstance(pull_request, dict)
        and pull_request.get("merged_at")
        and isinstance(pull_request.get("user"), dict)
        and str(pull_request["user"].get("login", "")).lower()
        in {"renovate[bot]", "renovate-bot"}
    ]

    if not renovate_prs:
        return None

    return max(renovate_prs, key=lambda pull_request: pull_request["merged_at"])


def remove_configured_files(
    repo_dir: Path,
    paths: list[str],
    excluded_paths: set[str],
) -> None:
    for path in paths:
        relative = Path(path)

        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"Invalid removal path: {path}")

        if is_excluded_path(relative.as_posix(), excluded_paths):
            print(f"Skipping repo excluded file removal: {path}")
            continue

        target = repo_dir / relative

        if not target.parent.resolve().is_relative_to(repo_dir.resolve()):
            raise ValueError(f"Removal path escapes repository: {path}")

        if target.is_symlink() or target.is_file():
            print(f"Removing configured file: {path}")
            target.unlink()
        elif target.exists():
            raise ValueError(f"Removal target is not a file: {path}")


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


def render_sync_pr_body(
    defaults: dict,
    report: list[dict],
    source_pr: dict | None,
) -> str:
    body = defaults["pr_body"].rstrip()

    if source_pr:
        title = source_pr.get("title", "Renovate update")
        url = source_pr.get("html_url")
        source_body = source_pr.get("body") or ""
        source_body = re.sub(
            r"<!--renovate-debug:.*?-->",
            "",
            source_body,
            flags=re.DOTALL,
        ).strip()

        body += "\n\n## Source Renovate PR\n\n"
        if url:
            body += f"**[{title}]({url})**\n\n"
        else:
            body += f"**{title}**\n\n"
        if source_body:
            body += source_body + "\n"

    body += "\n"
    body += render_sync_report(report)
    return body


def create_pr_if_needed(
    repo_name: str,
    branch: str,
    base_branch: str,
    defaults: dict,
    report: list[dict],
    source_pr: dict | None,
) -> str | None:
    body = render_sync_pr_body(defaults, report, source_pr)

    if pr_exists(repo_name, branch):
        print(f"Open PR already exists for {repo_name}:{branch}")
        existing = run(
            [
                "gh", "pr", "list",
                "--repo", repo_name,
                "--head", branch,
                "--state", "open",
                "--json", "url",
                "--jq", ".[0].url",
            ],
            capture=True,
        )
        existing_url = existing.strip()
        if existing_url:
            run(
                ["gh", "pr", "edit", existing_url, "--body", body],
                capture=True,
            )
        return existing_url or None

    url = run(
        [
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
        ],
        capture=True,
    )
    return url.strip() or None


def sync_repo(repo: dict, config: dict, source_pr: dict | None) -> str | None:
    defaults = config["defaults"]

    repo_name = repo["name"]
    short_name = repo_short_name(repo_name)
    base_branch = repo.get("base_branch", defaults["base_branch"])
    branch = f"{defaults['branch_prefix']}/{short_name}"
    topics = get_repo_topics(repo_name)
    report: list[dict] = []

    token = os.environ["GH_TOKEN"]
    clone_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / short_name

        run(["git", "clone", clone_url, str(repo_dir)])
        run(["git", "checkout", base_branch], cwd=repo_dir)
        run(["git", "checkout", "-B", branch], cwd=repo_dir)

        apply_sources(repo, repo_dir, repo_name, short_name, topics, base_branch, branch, config, report)
        apply_explicit_files(repo, repo_dir, repo_name, short_name, topics, base_branch, branch, config, report)
        remove_configured_files(
            repo_dir,
            defaults.get("remove_paths", []),
            set(repo.get("exclude", [])),
        )

        if not has_changes(repo_dir):
            print(f"No changes for {repo_name}")
            return None

        commit_message = resolve_commit_message(repo, defaults)

        run(["git", "add", "."], cwd=repo_dir)
        run(["git", "commit", "-m", commit_message], cwd=repo_dir)
        run(["git", "push", "--force", "origin", branch], cwd=repo_dir)

        return create_pr_if_needed(repo_name, branch, base_branch, defaults, report, source_pr)


def write_summary(results: list[dict]) -> None:
    lines = [
        "# Sync summary",
        "",
        "| Repository | Status | PR |",
        "|---|---|---|",
    ]

    for r in results:
        repo = r["repo"]
        if r["status"] == "error":
            status = "❌ error"
            pr_cell = f"`{r['error'][:120]}`"
        elif r["pr_url"]:
            status = "✅ created"
            pr_cell = f"[PR]({r['pr_url']})"
        else:
            status = "⏭️ no changes"
            pr_cell = "—"

        lines.append(f"| `{repo}` | {status} | {pr_cell} |")

    content = "\n".join(lines) + "\n"
    print(content)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(content)


def main() -> None:
    with CONFIG_PATH.open() as f:
        config = yaml.safe_load(f)

    validate_excluded_blocks(config)

    source_pr = get_merged_renovate_pr()
    if source_pr:
        print(f"Sync source Renovate PR: {source_pr['html_url']}")

    results: list[dict] = []

    for repo in config.get("repositories", []):
        repo_name = repo["name"]
        try:
            pr_url = sync_repo(repo, config, source_pr)
            results.append({"repo": repo_name, "status": "ok", "pr_url": pr_url, "error": None})
        except Exception as e:
            print(f"[ERROR] {repo_name}: {e}")
            results.append({"repo": repo_name, "status": "error", "pr_url": None, "error": str(e)})

    write_summary(results)

    if any(r["status"] == "error" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
