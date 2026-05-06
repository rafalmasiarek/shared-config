  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "{{ dependabot_interval }}"
    open-pull-requests-limit: {{ dependabot_open_pr_limit }}
    labels:
      - "dependencies"
      - "npm"
    commit-message:
      prefix: "{{ dependabot_commit_prefix }}"
    ignore:
      - dependency-name: "eslint"
        versions: ["5.x"]
    allow:
      - dependency-type: "direct"