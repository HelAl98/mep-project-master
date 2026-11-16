# Installation and project isolation

The release includes 16 skills: mep-project-master and its 15 registered siblings.
Resolve `scripts/master.py` relative to the selected SKILL.md, and `skills_root`
to that skill directory's parent. Do not mix global and project-local helper versions.

## User-global use

The normal skills location is `~/.agents/skills`; native role files, if configured,
live in `~/.codex/agents`. Expand these paths on the actual machine. This release
does not require the original development workspace. Existing global roles need
no replacement for this code update. A new chat can load the updated instructions.

Main handles initialization and mappings internally for a one-request procurement
task. For legacy workflows, `init --skills-root ABSOLUTE_SKILLS_ROOT` creates only
configuration, and the selected Guided/Automatic policy controls progression.
Never put project sources, SQLite, archives or exports in an installation directory.

Example request: `$mep-project-master Prepare mechanical procurement for the
project at [path]. Use a separate project database, continue independent work,
show material conflicts and decisions, and deliver Excel and Word for review.
Do not issue the selected scope until I confirm it.`

## Repository-local use

Open the repository containing `.agents/skills/` and its scoped `AGENTS.md`.
Its six `.codex/agents/` definitions are optional preferred native roles, not
verified model availability. Their instructions resolve from the repository.
Manual delegation is default; critical review requires separate authorization.
Use the Main fallback when native roles are unavailable.

The generic procurement integration fixture is validated separately from full
legacy stage execution. See validation-limits.md. No project is processed just
because installation, discovery or a folder open occurred.
