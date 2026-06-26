# Agent Team spawn prompts — vestaboard-ai-haiku

Enable teams first (one of):

- run `.claude/launch-team.fish`, or
- `set -x CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS 1` then `claude` (fish), or
- add `{"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}}` to `.claude/settings.json` (already
  done by the scaffold).

Then paste a prompt below to the team lead. After the team spawns, press `Shift+Tab` to lock the
lead into coordination-only mode.

---

## Security review swarm

> Create a read-only security review team for this repository. Each teammate uses only
> Read, Grep, Glob, and Bash (the latter only for non-mutating scanners and git). Spawn one
> teammate per scope:
>
> - `auth-reviewer`: Authentication & authorization — token issuance/validation, session lifecycle, access-control checks, and privilege-escalation paths.
> - `input-reviewer`: Input validation & injection — untrusted input handling, SQL/command/template injection, unsafe deserialization, and path traversal.
> - `supplychain-reviewer`: Dependencies & supply chain — lockfile integrity, known-vulnerable dependencies, post-install scripts, version pinning, and provenance.
>
> Each teammate audits only its own scope and returns a severity-ranked table
> (CRITICAL/HIGH/MEDIUM/LOW/INFO) with file:line locations. Once all teammates have reported,
> have them cross-challenge each other's findings, drop false positives, and converge on a single
> merged, severity-ranked report. No teammate may modify any file.

---

## Notes

- For deeper coverage, give each teammate its own git worktree (recommended for 4+ teammates).
- Keep spawn prompts rich: teammates start with a blank conversation, so name the files,
  entrypoints, and conventions they should focus on. `CLAUDE.md` covers the shared baseline.
- Swap "security review" for any read-heavy, parallelizable task (architecture review, test-gap
  analysis, dependency-upgrade impact). Teams shine when teammates work distinct scopes and then
  reconcile.
