# Git Commit and Pull Request Skill

A GitHub Copilot Agent Skill for minimal, action-oriented Git workflows focused on commits, pushes, and Pull Request draft content.

## Installation

Copy this directory into:

```text
.github/skills/gitbot/
```

The resulting structure should be:

```text
.github/
└── skills/
    └── gitbot/
        ├── README.md
        └── SKILL.md
```

## Important

This skill enforces strict command policies to keep Git workflows predictable and concise.

For commit workflows, it allows only status and diff analysis before confirmation, then add, commit, and push.

For Pull Request workflows, it allows only commit-history analysis between branches.

## Scope

The skill governs:

- Commit message generation in Conventional Commit format.
- Commit confirmation before execution.
- Minimal commit and push execution flow.
- Pull Request title generation from commit history.
- Pull Request description generation from commit history.
- Concise and action-oriented response style.

It intentionally does not govern:

- Code implementation changes.
- File diff analysis for Pull Request drafting.
- Branching strategy design.
- Repository administration.
- CI/CD configuration.

## Workflow Summary

### Commit workflow

1. Inspect with `git status`.
2. Inspect with `git diff`.
3. Propose one concise English Conventional Commit message.
4. Ask for explicit confirmation.
5. Execute:
   - `git add .`
   - `git commit -m "<confirmed message>"`
   - `git push`

### Pull Request workflow

1. Ask for branches if missing: base -> head.
2. Compare commits using `git log` with base..head.
3. Generate one concise English PR title.
4. Generate a concise PR description from differing commits only.
5. Ask for confirmation before any further action.

## Final Rule

Use the minimum Git commands necessary for the requested operation, and never mix commit and Pull Request workflows.
