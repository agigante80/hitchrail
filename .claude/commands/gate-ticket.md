<!-- gate-ticket-version: 3 -->

Run the ticket readiness gate on a GitHub issue in `agigante80/hitchrail`.

## Usage

Accepted argument: `<issue-number>` (required)

Example: `/gate-ticket 44`

## Steps

Use the Agent tool with `subagent_type: ticket-gate`, passing the issue number as the prompt.

The ticket-gate agent handles all steps:

1. Template version check against `.github/ISSUE_TEMPLATE/`, auto-synthesising missing sections
   rather than blocking
2. Fetches the issue with `gh`
3. Reads project context: `.claude/CLAUDE.md` (not the repository root; the root stays lean),
   `docs/tech-guidelines.md`, `docs/guides/ticket-standards.md`, the design spec and the current
   phase plan
4. Runs 5 core agents (Security, Architect, Developer, QA, **Blast Radius**) plus dynamic agents
   selected by labels and content
5. Compiles and posts the scorecard as a GitHub comment
6. Returns PASS or BLOCKED with specific required changes

All agents must score 10/10 for the ticket to be considered implementation ready.

## Notes for this repository

- The fifth core agent is **Blast Radius**, not GDPR. Hitchrail stores no personal data and has
  no database; what it does have is arbitrary code execution as the user. The reasoning lives in
  `docs/guides/ticket-standards.md` section 5.
- An **area label is required** and blocks without one. One per module: `config`, `discovery`,
  `tmux`, `procs`, `claude-ipc`, `ram`, `events`, `engine`, `security`, `server`, `web`, `cli`,
  plus `packaging`, `infrastructure` and `documentation`. The canonical list lives in
  `docs/guides/ticket-standards.md`. A missing type label only warns.
- A `security` label makes every agent run, not only the triggered ones.
- Much of the codebase does not exist yet. "Greenfield area, no existing patterns in scope" is
  context for the Architect agent, not a deduction.
