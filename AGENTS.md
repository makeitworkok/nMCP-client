# Agent Operating Rules

Purpose: keep the agent consistent, safe, and deterministic when operating Niagara through nMCP tools.

## Priority Rules

1. Validate scope before mutation.
2. Prefer plan -> validate -> apply for multi-step wiresheet work.
3. Never write outside allowlisted roots.
4. If a write payload fails validation, stop retry loops and switch to schema correction.
5. Record every new failure pattern in docs/agent-lessons.md.


## Standard Write Workflow

**Sequencing Rule:**
Always create all points/components first, then add logic blocks (e.g., control, math, compare), then wire/link last. Never attempt to wire or configure logic for components that do not exist yet.

1. Discover target root and confirm path access.
2. Gather existing components and candidate types.
3. Build operation list.
4. Run nmcp.wiresheet.plan with strict true.
5. If valid, run nmcp.wiresheet.apply.
6. Verify results using component.search/component.children and wiresheet.links when relevant.

## Wiresheet Operation Contract

Each operation in operations must include type.

Allowed values:
- createComponent
- setSlot
- link
- addCompositePin

Minimum createComponent fields:
- type: createComponent
- parentOrd
- name
- componentType

Facets note:
- When supported by the target component type, facets may be supplied directly on createComponent as a whole facets object.

Minimum setSlot fields:
- type: setSlot
- componentOrd (absolute component ORD under an allowlisted root)
- slot
- value

Facet slot rule:
- For facet updates, write slot=facets as a whole value.
- Do not write nested facet sub-slots like facets.units.

Minimum link fields:
- type: link
- from (absolute source slot endpoint under an allowlisted root)
- to (absolute target slot endpoint under an allowlisted root)

Link endpoint rule:
- Never use bare slot tokens or shorthand in link endpoints (examples: out, inA, out/out).
- Discover real endpoints first, then use full absolute endpoint strings for from/to.

## Error Handling Rules

1. If error contains unsupported type: null:
- Treat as missing or invalid operation type.
- Regenerate payload with explicit operation type fields.

2. If error contains Path not in allowlisted roots:
- Stop writes on that path.
- Discover allowed roots via component.children from known roots.
- Rebuild plan using an allowlisted root.

3. If repeated validation failures occur 2+ times:
- Switch to a minimal one-operation dry run.
- Expand only after first operation validates.

## Response Style During Execution

1. Announce intent in one short sentence.
2. Show step number and action.
3. On error, provide root cause and exact next corrective action.
4. Avoid optimistic claims before tool success.

## Learning Loop

After each incident:
1. Add a short entry to docs/agent-lessons.md.
2. Include trigger, root cause, corrective pattern, and reusable snippet.
3. Prefer updating existing pattern entries over adding duplicates.
