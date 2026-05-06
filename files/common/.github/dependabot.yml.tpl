# Added from shared-config: {{ source }}

version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    labels:
        - "dependencies"
        - "github-actions"
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"