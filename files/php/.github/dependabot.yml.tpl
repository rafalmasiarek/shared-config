  - package-ecosystem: "composer"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    labels:
      - "dependencies"
      - "php"
      - "composer"
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"