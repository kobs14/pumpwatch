---
name: post-session
description: Update PumpWatch state files (PROJECT_STATUS.md, tasks/lessons.md, tasks/todo.md) at the end of a session, and print the proposed conventional commit message. Use after /verify passes. Does NOT run git commit — the user owns that step.
---

# Post-session documentation pass

Encodes CLAUDE.md §Session Workflow steps 5–6. Run after `/verify` passes and before the user commits.

## Pre-flight

- Confirm `/verify` was just run and passed. If not, refuse and tell the user to run `/verify` first.
- Read `PROJECT_STATUS.md`, `tasks/todo.md`, `tasks/lessons.md` to find the current session number and title.
- Read `git status --short` and `git diff --stat HEAD` to discover which files were actually touched.

## Steps

### 1. Update `PROJECT_STATUS.md`

- **Session Plan table:** flip the current session row from `⬜` to `✅ done` and add a one-line `Notes` cell summarizing what shipped.
- **Header fields:**
  - `Phase:` → `Post-Session N`
  - `Last Session Completed:` → `Session N — <Title>`
  - `Next Session:` → `Session N+1 — <Next Title>` (look it up in the table)
  - `Last Updated:` → today's absolute date (`YYYY-MM-DD`)
- **Files Created So Far:** append a new `Session N:` block listing actual paths from `git status --short` (split into "created" vs "modified" if the section already does that).
- **Architectural Decisions Locked:** if any new decision was made and it warrants persistence, append a numbered entry. Then prompt the user to also run `/adr <slug>` to file the full ADR — do not run `/adr` automatically; the user picks the title.
- **Risks / Watch Items:** add or revise entries if new risks were realized or old ones resolved.

### 2. Append to `tasks/lessons.md`

Use the file's own format block:

```markdown
## Session N — YYYY-MM-DD

- **Lesson:** <one-sentence summary>
  **Context:** <what we were doing when it came up>
  **Action:** <what we changed, or what should change>
```

One bullet per surprise / gotcha / non-obvious decision. Skip lessons that just restate CLAUDE.md — only write what would help a future session avoid a mistake or make a better choice. Always include both *what* and *why* so the lesson is actionable in a slightly different context.

### 3. Reset `tasks/todo.md`

- Replace the active section with the next session's title:
  ```markdown
  ## Active: Session N+1 — <Next Title>
  ```
- Move any unfinished items from this session into a `### Carry-over from Session N` subsection.
- Preserve any `### Future cleanup (still open)` section as-is unless items were resolved this session.

### 4. (Optional) Suggest an ADR

If step 1 added a new architectural decision, print:
> "New architectural decision detected: '<decision>'. Run `/adr <suggested-slug>` to file it under `docs/adr/`."

Do not invoke `/adr` automatically.

### 5. Propose the commit message

Print, but do NOT execute:

```
Proposed commit (CLAUDE.md format):

<type>: <description> (Session N)

Body (if needed):
- <bullet 1>
- <bullet 2>
```

`<type>` is one of `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. Look at recent `git log --oneline -10` for the style.

### 6. STOP

Do not run `git commit`. CLAUDE.md and the harness rules require explicit user approval for commits. Tell the user the docs are updated and the commit message is ready for them to run.

## Output shape

```
## Post-session: Session N complete

**State files updated:**
- PROJECT_STATUS.md  (table row, header, files block)
- tasks/lessons.md   (N new entries)
- tasks/todo.md      (reset to Session N+1)

**ADR suggestion:** <slug or "none">

**Proposed commit:**
<type>: <description> (Session N)
```
