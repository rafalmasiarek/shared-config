# shared-config

Centralized repository for synchronizing shared configuration files across multiple GitHub repositories.

## Structure

```text
files/common/          # always applied
files/<github-topic>/  # applied when a repository has the matching GitHub topic
files/shared/          # manually referenced files from repos.yml
repos/<repo-name>/     # repository-specific overrides
```

## Priority Order

Files are applied in the following order:

```text
files/common/
files/<github-topic>/
repos/<repo-name>/
repositories[].files[]
```

Later layers override earlier ones.

## Repository Configuration

Repositories are defined in `repos.yml`.

```yaml
repositories:
  - name: org/api-php

  - name: org/app-frontend
```

## Explicit File Rules

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

## File Modes

```text
overwrite  # default, replaces the destination file
append     # appends content to the destination file
```

## GitHub Secret

Add this GitHub Actions secret:

```text
SHARED_CONFIG_SYNC_TOKEN
```

The token must be able to clone repositories, push branches, create pull requests, and read repository topics.
