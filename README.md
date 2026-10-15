# shared-config

Centralized repository for synchronizing shared configuration files across multiple GitHub repositories.

This repository keeps common files such as GitHub Actions workflows, triage rules, Dependabot language-ecosystem configuration, linters, CI helpers, and repository-specific overrides in one place. Renovate is configured in this repository to update GitHub Actions references in workflows and shared YAML files under `files/`.

The sync workflow clones configured repositories, applies matching shared files, commits the changes to a dedicated branch, and opens a pull request.

Renovate PRs include the version-change table, available release notes/changelogs, warnings, and a review checklist. Major GitHub Actions updates require approval in the Dependency Dashboard. GitHub Actions are pinned to commit digests when Renovate supports it, improving supply-chain integrity. The PR asks reviewers to check advisories, but Renovate's alert coverage is not a complete security audit; verify upstream advisories and run project checks before merging.

## Structure

```text
files/common/          # always applied to every repository
files/<github-topic>/  # applied when a repository has the matching GitHub topic
files/shared/          # manually referenced files from repos.yml
repos/<repo-name>/     # repository-specific overrides
repos.yml              # sync configuration
scripts/sync.py        # sync engine
```

## Priority Order

Files are applied in the following order:

```text
files/common/
files/<github-topic>/
repos/<repo-name>/
repositories[].files[]
```

Later layers override earlier ones when the same target path is used with `overwrite`.

Explicit file mappings from `repositories[].files[]` are applied last.

## Repository Configuration

Repositories are defined in `repos.yml`.

```yaml
repositories:
  - name: org/api-php

  - name: org/app-frontend
```

Each repository is identified by its full GitHub name:

```text
owner/repository
```

The sync engine reads GitHub topics from each repository and uses them to decide which topic-based directories should be applied.

For example, if a repository has these GitHub topics:

```text
php
docker
github-actions
```

Then these directories are applied when they exist:

```text
files/php/
files/docker/
files/github-actions/
```

## Default Configuration

Example `repos.yml`:

```yaml
defaults:
  base_branch: main
  branch_prefix: shared-config
  commit_message: "chore: sync shared config"
  pr_title: "chore: sync shared config"
  pr_body: |
    Automated sync from shared-config.

repositories:
  - name: org/api-php

  - name: org/app-frontend
```

## Defaults

The `defaults` section controls Git and pull request behavior.

```yaml
defaults:
  base_branch: main
  branch_prefix: shared-config
  commit_message: "chore: sync shared config"
  pr_title: "chore: sync shared config"
  pr_body: |
    Automated sync from shared-config.
```

Available options:

```text
base_branch      # target branch for pull requests
branch_prefix    # prefix for sync branches
commit_message   # commit message used by the sync engine
pr_title         # pull request title
pr_body          # pull request body
remove_paths     # optional files to remove from every configured destination repository
```

`remove_paths` is an optional global cleanup policy. It is applied after shared and explicit files and respects each repository's `exclude` list. Paths must be relative files within the destination repository; directories and paths containing `..` are rejected. The current configuration does not set `remove_paths`.

The sync branch is generated as:

```text
<branch_prefix>/<repo_short_name>
```

For example:

```text
shared-config/api-php
```

## Explicit File Rules

Explicit file rules are configured per repository under `repositories[].files[]`.

```yaml
repositories:
  - name: org/api-php
    files:
      - from: files/shared/.gitignore.php
        to: .gitignore
        mode: append

      - from: repos/api-php/.gitignore
        to: .gitignore
        mode: append

      - from: files/shared/renovate.json
        to: renovate.json
        mode: overwrite
```

Fields:

```text
from  # source file path in this repository
to    # target file path in the destination repository
mode  # optional file mode, defaults to overwrite
```

Explicit file rules are useful for files that should not be applied automatically by topic, or for shared files that need a custom target path.

## File Modes

Supported file modes:

```text
overwrite  # default, replaces the destination file
append     # appends or merges content into the destination file
```

### overwrite

The `overwrite` mode replaces the destination file with the source file.

```yaml
repositories:
  - name: org/api-php
    files:
      - from: files/shared/triage-rules.yml
        to: .github/triage-rules.yml
        mode: overwrite
```

If `mode` is omitted, `overwrite` is used by default.

### append

The `append` mode behaves differently depending on the destination file type.

```yaml
repositories:
  - name: org/api-php
    files:
      - from: files/shared/.gitignore.php
        to: .gitignore
        mode: append
```

For plain text files, content is appended with a marker comment:

```text
# Added from shared-config: files/shared/.gitignore.php
```

For YAML files, content is appended as YAML text and the final file is validated with `yaml.safe_load`.

For JSON files, objects and arrays are merged structurally.

## Policy-Based File Modes

File modes can also be configured globally through `policies`.

```yaml
policies:
  files/js/.github/dependabot.yml.tpl:
    mode: append

  files/php/.github/dependabot.yml.tpl:
    mode: append

  files/python/.github/dependabot.yml.tpl:
    mode: append

  files/docker/.github/dependabot.yml.tpl:
    mode: append
```

The mode resolution order is:

```text
repositories[].files[].mode
policies.<source-path>.mode
overwrite
```

This means explicit file mappings can override global policies.

## Excluding Files

A repository can exclude target paths from all synchronization operations: automatic source tree application, explicit mappings, and configured removals.

```yaml
repositories:
  - name: org/legacy-app
    exclude:
      - .github/workflows/ci.yml
      - .github/dependabot.yml
```

Paths are destination paths. Excluding a file preserves its current version and prevents it from being applied by automatic copying, explicit mappings, or global cleanup. This excludes the whole file, not an individual dependency or action reference inside it.

To preserve only a specific fragment while syncing the rest of a file, mark the block in the shared source file with comment markers:

```yaml
# shared-config:block:start: checkout
- uses: actions/checkout@v5
# shared-config:block:end: checkout
```

Then configure the destination repository to preserve the existing contents of that named block:

```yaml
repositories:
  - name: org/legacy-app
    exclude_blocks:
      - path: .github/workflows/ci.yml
        name: checkout
```

On sync, the existing marked block from `org/legacy-app` is retained while the rest of `ci.yml` receives updates. The excluded block must already be marked in both the shared source and the destination file; otherwise sync fails rather than accidentally replacing it. To exclude a dependency bump safely, first add the markers without changing the dependency version and sync that change to destinations; then enable `exclude_blocks` before merging the version bump. Block exclusions require `overwrite` mode.

## Templates

Files ending with `.tpl` are rendered using Jinja2 before being written to the destination repository.

The `.tpl` suffix is removed from the target path automatically.

For example, `files/common/config.yml.tpl` is written as `config.yml` in destination repositories. This applies both to automatically discovered files and explicit file mappings.

Dependabot configuration is distributed only for repositories with matching `js`, `php`, `python`, or `docker` topics. The shared configuration includes npm, Composer, pip, and Docker updates; it does not configure the `github-actions` ecosystem because Renovate manages updates to shared GitHub Actions.

## Template Variables

Templates receive a predefined context from the sync engine.

### System Variables

Available system variables:

```text
repo              # full repository name, for example org/api-php
repo_short_name   # repository name without owner, for example api-php
topics            # list of GitHub topics
topics_csv        # GitHub topics joined with commas
source            # source path in shared-config
target            # target path in destination repository
base_branch       # target base branch
sync_branch       # generated sync branch
```

Example usage:

```jinja2
Repository: {{ repo }}
Short name: {{ repo_short_name }}
Source: {{ source }}
Target: {{ target }}
Base branch: {{ base_branch }}
Sync branch: {{ sync_branch }}
Topics: {{ topics_csv }}
```

Conditional examples:

```jinja2
{% if repo == "org/api-php" %}
# repository-specific content
{% endif %}

{% if repo_short_name == "api-php" %}
# short-name specific content
{% endif %}

{% if "php" in topics %}
# PHP-specific content
{% endif %}

{% if "docker" in topics %}
# Docker-specific content
{% endif %}
```

## Global Variables

Global variables can be defined in the `vars` section.

```yaml
vars:
  default_branch: main
  enable_feature: true
```

They are available in every template:

```jinja2
branch: "{{ default_branch }}"
{% if enable_feature %}
feature_enabled: true
{% endif %}
```

## Topic Variables

Topic-specific variables can be defined in `topic_vars`.

```yaml
topic_vars:
  php:
    runtime: php

  js:
    runtime: node

  docker:
    docker_enabled: true
```

When a repository has a matching GitHub topic, those variables are added to the template context.

Example:

```jinja2
{% if runtime | default("") == "php" %}
# PHP runtime configuration
{% endif %}

{% if docker_enabled | default(false) %}
# Docker configuration
{% endif %}
```

## Repository Variables

Repository-specific variables can be defined under `repositories[].vars`.

```yaml
repositories:
  - name: org/api-php
    vars:
      default_branch: stable
      custom_ci_enabled: true
```

Example:

```jinja2
branch: "{{ default_branch }}"

{% if custom_ci_enabled | default(false) %}
# custom CI enabled
{% endif %}
```

Repository variables override global variables and topic variables.

## File Variables

File-specific variables can be defined in `file_vars`.

```yaml
file_vars:
  files/common/config.yml.tpl:
    config_version: 2
```

Example:

```jinja2
version: {{ config_version }}
```

File variables are matched by source path.

## Variable Priority

Template variables are merged in this order:

```text
system variables
vars
topic_vars
repositories[].vars
file_vars
```

Later values override earlier values.

This means `file_vars` have the highest priority in the current implementation.

Recommended safe usage for optional variables:

```jinja2
{% if custom_flag | default(false) %}
# enabled
{% endif %}
```

Because templates use strict undefined variables, referencing an undefined variable directly may fail.

Avoid this:

```jinja2
{% if custom_flag %}
# may fail when custom_flag is not defined
{% endif %}
```

Use this instead:

```jinja2
{% if custom_flag | default(false) %}
# safe
{% endif %}
```

## Example Repository With Overrides

```yaml
repositories:
  - name: org/api-php
    base_branch: main
    vars:
      default_branch: stable
    files:
      - from: files/shared/triage-rules.yml
        to: .github/triage-rules.yml
        mode: overwrite

      - from: files/shared/.gitignore.php
        to: .gitignore
        mode: append
```

This repository will:

```text
use main as the base branch
override default_branch
copy triage-rules.yml explicitly
append shared PHP .gitignore content
```

## Sync Report

When a pull request is created, the sync engine appends a sync report to the pull request body.

When the triggering commit belongs to a merged PR authored by `renovate[bot]` or `renovate-bot`, the sync PR also includes that source PR's title, link, and description (including any release notes, review checklist, and security information Renovate provided). Existing open sync PRs have their body refreshed on each sync run. The source PR body is copied as provided, except for Renovate's hidden debug metadata.

The report contains:

```text
source path
target path
mode
status
file size
source SHA256
source modified time
```

Possible statuses:

```text
added
modified
unchanged
```

## GitHub Secret

Add this GitHub Actions secret:

```text
SHARED_CONFIG_SYNC_TOKEN
```

The token must be able to:

```text
clone configured repositories
push branches
create pull requests
read repository topics
read merged PR details in shared-config
```

Recommended permissions for a fine-grained GitHub token:

```text
Contents: Read and write
Pull requests: Read and write
Metadata: Read-only
Administration: Read-only, if required for topic access in your setup
```

The workflow should expose it as `GH_TOKEN`:

```yaml
env:
  GH_TOKEN: ${{ secrets.SHARED_CONFIG_SYNC_TOKEN }}
```

## Notes

The sync engine uses GitHub topics to select topic-based configuration directories.

Source files are copied and configured removal paths are deleted. Directories are created automatically as needed.

`.gitkeep` files are ignored by default.

Template rendering is only applied to files ending with `.tpl`.

For `.tpl` files, the destination path is generated by removing the `.tpl` suffix. Root-level files such as `renovate.json` configure this repository and are not copied to destination repositories; Renovate's current configuration is preserved.

Pull requests are not duplicated. If an open pull request already exists for the generated sync branch, the script skips creating a new one.
