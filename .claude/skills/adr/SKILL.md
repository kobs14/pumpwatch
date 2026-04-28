---
name: adr
description: Scaffold a new Architecture Decision Record under docs/adr/. Auto-numbers from the existing index, creates NNN-<slug>.md with the Context/Decision/Consequences template, and updates docs/adr/README.md. Invoke as /adr <slug>.
---

# Scaffold a new ADR

Encodes CLAUDE.md §Documentation Discipline: "every architectural decision worth more than two sentences gets an ADR in `docs/adr/NNN-title.md`. Format: context, decision, consequences."

## Inputs

- `<slug>` — kebab-case short identifier from the user (e.g., `bot-webhook-mode`, `price-snapshot-partitioning`).
- Optional `<title>` — human title; if not given, derive from slug (`bot-webhook-mode` → `Bot webhook mode`).

## Steps

### 1. Determine the next number

- Read `docs/adr/README.md` and list `docs/adr/*.md` (excluding README.md).
- Find the highest existing numeric prefix (e.g., `020-...`).
- Next number is highest + 1, three-digit zero-padded (e.g., `021`).

### 2. Create the ADR file

Path: `docs/adr/NNN-<slug>.md`

Template:

```markdown
# ADR NNN — <Title>

## Context

<What changed or what problem prompted this decision. Reference any prior
ADRs being superseded or extended. Include enough state for a future
reader to reconstruct why we were making this call.>

## Decision

<The actual call. Be concrete: name the module, the setting, the
behaviour. If alternatives were considered and rejected, name them and
say why in one line each.>

## Consequences

<What becomes easier. What becomes harder. What we now can't do without
writing another ADR. Include any operational impact (new env vars, new
service, new permissions).>
```

### 3. Update the index

In `docs/adr/README.md`, append a row to the index table:

```markdown
| NNN | [<Title>](NNN-<slug>.md) | Session N |
```

`Session N` = the current session per `PROJECT_STATUS.md`.

### 4. (If applicable) Update `PROJECT_STATUS.md`

If this ADR captures a decision currently inlined under "Architectural Decisions Locked" in `PROJECT_STATUS.md`, replace the inline entry with a one-line reference: `See ADR-NNN`.

### 5. Print the new path

Tell the user the file is scaffolded and ready for them to fill in the body. Do NOT invent the body content — the user owns the decision narrative.

## Output shape

```
## ADR NNN — <Title>

Created:  docs/adr/NNN-<slug>.md
Updated:  docs/adr/README.md (index row added)

Next: fill in the Context / Decision / Consequences body.
```

## Notes

- ADRs are append-only. To revisit a decision, write a new ADR that supersedes the old one and update the old ADR's status to "Superseded by ADR-NNN" — never edit a decision in place.
- One-line decisions live inline in `PROJECT_STATUS.md` (currently #1–#7, #11, #21). Use a full ADR file when the rationale is more than two sentences.
