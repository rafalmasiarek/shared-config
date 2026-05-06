# shared-config

Centralized repository for synchronizing shared configuration files across multiple GitHub repositories.

This repository keeps common files such as GitHub Actions workflows, Dependabot configuration, triage rules, linters, CI helpers, and repository-specific overrides in one place.

The sync workflow clones configured repositories, applies matching shared files, commits the changes to a dedicated branch, and opens a pull request.

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

vars:
  dependabot_interval: weekly
  dependabot_open_pr_limit: 5
  dependabot_commit_prefix: chore(deps)

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
```

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

A repository can exclude target paths from automatic source tree application.

```yaml
repositories:
  - name: org/php-images
    exclude:
      - .github/dependabot.yml
```

This is useful when a repository should receive most topic-based files, but skip a specific one.

The `exclude` list is checked against target paths generated during automatic tree application.

Explicit files from `repositories[].files[]` are still applied unless they are not listed there.

## Templates

Files ending with `.tpl` are rendered using Jinja2 before being written to the destination repository.

The `.tpl` suffix is removed from the target path automatically.

For example:

```text
files/php/.github/dependabot.yml.tpl
```

is written as:

```text
.github/dependabot.yml
```

This applies both to automatically discovered files and explicit file mappings.

Example template:

```jinja2
version: 2
updates:
{% if "php" in topics %}
  - package-ecosystem: "composer"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"
{% endif %}

{% if "docker" in topics %}
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"
{% endif %}
```

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
  dependabot_interval: weekly
  dependabot_open_pr_limit: 5
  dependabot_commit_prefix: chore(deps)
```

They are available in every template:

```jinja2
schedule:
  interval: "{{ dependabot_interval }}"
open-pull-requests-limit: {{ dependabot_open_pr_limit }}
commit-message:
  prefix: "{{ dependabot_commit_prefix }}"
```

## Topic Variables

Topic-specific variables can be defined in `topic_vars`.

```yaml
topic_vars:
  php:
    dependabot_ecosystem: composer
    runtime: php

  js:
    dependabot_ecosystem: npm
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
      dependabot_open_pr_limit: 10
      custom_ci_enabled: true
```

Example:

```jinja2
open-pull-requests-limit: {{ dependabot_open_pr_limit }}

{% if custom_ci_enabled | default(false) %}
# custom CI enabled
{% endif %}
```

Repository variables override global variables and topic variables.

## File Variables

File-specific variables can be defined in `file_vars`.

```yaml
file_vars:
  files/php/.github/dependabot.yml.tpl:
    dependabot_ecosystem: composer
    dependabot_directory: /
```

Example:

```jinja2
- package-ecosystem: "{{ dependabot_ecosystem }}"
  directory: "{{ dependabot_directory }}"
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

## Example Dependabot Template

Example file:

```text
files/php/.github/dependabot.yml.tpl
```

Content:

```jinja2
version: 2
updates:
  - package-ecosystem: "composer"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"

{% if "github-actions" in topics %}
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"
{% endif %}
```

Example policy:

```yaml
policies:
  files/php/.github/dependabot.yml.tpl:
    mode: append
```

## Example Repository With Overrides

```yaml
repositories:
  - name: org/api-php
    base_branch: main
    exclude:
      - .github/dependabot.yml
    vars:
      dependabot_open_pr_limit: 10
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
skip automatic .github/dependabot.yml application
override dependabot_open_pr_limit
copy triage-rules.yml explicitly
append shared PHP .gitignore content
```

## Sync Report

When a pull request is created, the sync engine appends a sync report to the pull request body.

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

Only files are copied. Directories are created automatically as needed.

`.gitkeep` files are ignored by default.

Template rendering is only applied to files ending with `.tpl`.

For `.tpl` files, the destination path is generated by removing the `.tpl` suffix.

Pull requests are not duplicated. If an open pull request already exists for the generated sync branch, the script skips creating a new one.
