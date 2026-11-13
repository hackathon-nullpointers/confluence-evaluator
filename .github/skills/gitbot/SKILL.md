---

name: gitbot
description: Create concise English Git commits following Conventional Commits and generate Pull Request titles and descriptions. Use this skill when the user asks to commit changes, push a commit, prepare a Pull Request, or compare commits between branches. For commits, inspect changes only with git status and git diff, ask the user to confirm the proposed commit message before committing, then add, commit, and push. For Pull Requests, use only git log to compare commits between the specified branches. Keep responses extremely concise and avoid unnecessary Git commands or explanations.

---

# Git Commit & Pull Request

## Purpose

Provide a minimal Git workflow for:

* Creating commits following Conventional Commits.
* Pushing commits to the remote repository.
* Generating Pull Request titles and descriptions.

Keep all interactions concise and action-oriented. Do not provide lengthy explanations unless explicitly requested.

---

# Repository Root Rule

All commit analysis and commit execution must run from the repository root.

For commits, run `git status`, `git diff`, `git add .`, `git commit`, and `git push` only from the repository root.

If the current working directory is not the repository root, change to the root first and then continue the workflow.

---

# Conventional Commits Rules

All generated commit messages MUST follow the Conventional Commits specification.

## Commit Message Format

Use the following format:

`<type>[optional scope][!]: <description>`

Examples:

* `feat: add payment retry flow`
* `fix(auth): handle expired access tokens`
* `refactor(quote): simplify detail mapping`
* `test(api): add login endpoint coverage`
* `docs: update installation instructions`
* `feat(api)!: replace legacy authentication contract`

The scope is optional and should identify the affected module, feature, or component when useful.

## Allowed Types

Use these conventional types:

* `feat`: Introduces a new feature.
* `fix`: Fixes a bug.
* `docs`: Documentation-only changes.
* `style`: Formatting or stylistic changes that do not affect behavior.
* `refactor`: Code restructuring without changing externally observable behavior.
* `perf`: Improves performance.
* `test`: Adds or modifies tests without changing production behavior.
* `build`: Changes build configuration, dependencies, or build tooling.
* `ci`: Changes CI/CD configuration or pipelines.
* `chore`: Maintenance tasks that do not fit another type.
* `revert`: Reverts a previous commit.

Do not invent new types such as `update`, `improvement`, or `changes`.

Choose the type that best represents the primary purpose of the changes. If multiple types apply, prioritize the main purpose instead of combining several types into one commit message.

## Description Rules

The description MUST:

* Be written in English.
* Be concise, clear, specific, and action-oriented.
* Start with a lowercase letter whenever practical.
* Use imperative wording where appropriate.
* Avoid a trailing period.
* Describe the primary change, not every modified file.
* Avoid vague descriptions such as `update code`, `fix changes`, or `improve functionality`.

Prefer:

`fix(auth): handle expired access tokens`

Avoid:

`update: implement some authentication improvements`

Do not include unnecessary implementation details or lengthy explanations.

## Breaking Changes

When the changes introduce a backward-incompatible modification:

* Add `!` immediately after the type or scope.
* If necessary, explain the breaking change in the commit body using `BREAKING CHANGE: <description>`.

Examples:

`feat(api)!: replace the authentication response format`

`feat(api): replace the authentication response format`

`BREAKING CHANGE: clients must use the new response structure`

Do not mark a change as breaking unless the available changes clearly establish backward incompatibility.

Do not invent breaking changes or commit bodies.

## Commit Type Selection

Determine the commit type exclusively from the information available in `git status` and `git diff`.

Examples:

* New endpoint or business capability: `feat`
* Incorrect validation or unexpected behavior: `fix`
* Internal restructuring with unchanged behavior: `refactor`
* Automated test coverage: `test`
* Documentation changes: `docs`
* Dependency updates: `build` or `chore`, depending on the purpose
* Pipeline configuration changes: `ci`
* Formatting without behavior changes: `style`
* Performance optimization: `perf`

If the purpose is ambiguous, choose the most appropriate type supported by the diff. Do not invent functionality or infer changes that are not visible.

---

# Commit Workflow

When the user asks to commit changes, follow this exact flow.

## 1. Inspect Repository Status

Use only:

```bash
git status
```

## 2. Inspect Changes

Use only:

```bash
git diff
```

Do not use `git log` during commit analysis.

Do not inspect branches or remote configuration unless required because the operation fails.

Do not inspect additional files using unrelated commands. Base the proposed message on `git status` and `git diff` only.

## 3. Generate Commit Message

Generate exactly one concise English commit message following the Conventional Commits rules.

Use:

`<type>[optional scope][!]: <description>`

The message must accurately represent the primary purpose of the changes.

Do not include a body or footer unless the user explicitly requests one or a clearly established breaking change requires additional explanation.

Before presenting the message, verify that:

* The type is valid.
* The scope, if present, is concise and relevant.
* The description is clear and specific.
* The message does not end with a period.
* The message does not invent functionality.
* Breaking-change notation is used only when justified.

---

# Commit Confirmation

Never create a commit before asking for explicit confirmation.

After generating the message, ask only for confirmation.

Example:

Commit message:

`fix(auth): handle expired access tokens`

Proceed?

Wait for explicit confirmation.

If the user rejects the message:

* Ask for the preferred message, or
* Propose another concise message following Conventional Commits.

If the user explicitly provides a commit message, validate it against Conventional Commits, display the proposed message, and request confirmation before committing.

If the provided message violates the convention, suggest a corrected version and request confirmation for that version.

Do not interpret the initial request to commit as confirmation of a message that has not yet been presented.

---

# Commit Execution

After confirmation, execute only the commands necessary to commit and push:

```bash
git add .
git commit -m "<confirmed message>"
git push
```

Use the exact confirmed commit message.

Do not modify the message after confirmation.

Do not execute unnecessary Git commands.

Do not run the following commands during the normal commit workflow:

```text
git log
git show
git branch
git checkout
git switch
git fetch
git pull
git reset
git stash
git remote
```

If an operation fails, report the relevant error and the minimum information required to continue. Do not automatically run additional Git commands outside the allowed workflow.

---

# Commit Result

After a successful operation, respond briefly.

Example:

Committed and pushed:

`fix(auth): handle expired access tokens`

Do not provide:

* Full Git command output.
* A list of changed files.
* A detailed explanation.
* Unrequested technical context.

If the operation fails, report only the relevant error and the minimum information required to continue.

---

# Pull Request Workflow

When the user asks to prepare a Pull Request, generate:

1. PR title.
2. PR description.

The PR content MUST be based exclusively on commits that exist in the head branch but not in the base branch.

Do not analyze file changes.

## Request Branches

If either branch is missing, ask:

Which branches should I compare?

`base -> head`

Never guess missing branches.

## Compare Branches

Use exactly one Git command to compare the branches:

```bash
git log --oneline <base>..<head>
```

Example:

```bash
git log --oneline develop..feature/payment-retry
```

Rules:

* `<base>` is the target branch.
* `<head>` is the source branch.
* The command returns commits reachable from `head` that are not reachable from `base`.
* Use the commit subjects to determine the overall purpose and summarize the changes.
* Do not execute any additional Git commands.
* Do not use `git diff`, `git status`, `git show`, or any other Git command during PR preparation.
* Do not inspect files or infer implementation details.
* Do not fetch branches automatically.

## Pull Request Title

Generate one concise title in English summarizing the overall purpose of the commits.

The title should be specific and action-oriented.

Examples:

* `Add payment retry handling`
* `Fix login validation`
* `Improve quote generation`

PR titles do not need to follow Conventional Commits unless explicitly requested.

## Pull Request Description

Generate a concise description based exclusively on the commit subjects returned by `git log`.

Preferred format:

```markdown
## Summary

- Add payment retry handling
- Update retry validation
- Improve error handling
```

Rules:

* Group related commits when appropriate.
* Remove redundant information.
* Do not invent functionality, testing, or business impact.
* Do not claim implementation details that cannot be established from commit subjects.
* If the commit subjects are insufficient, keep the description general rather than inventing details.

## Empty Results

If no commits are returned, respond:

`No commits found between the selected branches.`

## Pull Request Output

Present the result concisely:

Title:

`Add payment retry handling`

Description:

```markdown
## Summary

- Add payment retry handling
- Update retry validation
```

If the user only requests the title and description, do not perform additional actions.

Do not create or publish the PR unless explicitly requested and the required tooling is available.

---

# Git Command Policy

## Commit Workflow

Allowed commands:

```bash
git status
git diff
git add .
git commit -m "<confirmed message>"
git push
```

Follow the Conventional Commits rules and obtain explicit confirmation before committing.

## Pull Request Workflow

The only allowed Git command is:

```bash
git log --oneline <base>..<head>
```

Execute it exactly once per PR preparation request.

Do not execute `git status`, `git diff`, `git show`, or any other Git command during PR preparation.

---

# Workflow Separation

## Commit

```text
git status
    ↓
git diff
    ↓
generate Conventional Commit message
    ↓
ask for confirmation
    ↓
git add .
    ↓
git commit
    ↓
git push
```

## Pull Request

```text
request base/head if missing
    ↓
git log --oneline base..head
    ↓
generate PR title
    ↓
generate PR description
    ↓
show result
```

Never mix the commit and Pull Request workflows.

---

# Final Rule

Use the minimum Git commands necessary to accomplish the requested task.

For commits:

Inspect with `git status` and `git diff`, generate a Conventional Commit message, request explicit confirmation, then add, commit, and push.

For Pull Requests:

Compare branches using only `git log`, then generate a concise English title and description based exclusively on the differing commits.

Keep everything short, clear, accurate, and action-oriented.
