  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    labels:
      - "dependencies"
      - "python"
      - "pip"
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"