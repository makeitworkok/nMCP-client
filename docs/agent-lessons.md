# Agent Lessons Log

Use this file to persist incident learnings so the agent does not relearn from scratch.

## Entry Template

- Date:
- Trigger:
- Symptom/Error:
- Root Cause:
- Corrective Action:
- Reusable Payload or Prompt Pattern:
- Files Updated:

---

## 2026-05-20 - Wiresheet operation type missing

- Date: 2026-05-20
- Trigger: Creating BooleanWritable points via nmcp.wiresheet.apply
- Symptom/Error: Validation failed: Operation at index 0 has unsupported type: null
- Root Cause: operations entries omitted required type field
- Corrective Action: add type=createComponent to each create operation
- Reusable Payload or Prompt Pattern:
  - Always send operations with explicit type values.
  - Validate through nmcp.wiresheet.plan before apply.
- Files Updated:
  - AGENTS.md
  - docs/niagara-agent-playbook.md
  - docs/agent-lessons.md

---

## 2026-05-20 - Path not in allowlisted roots (guessed path)

- Date: 2026-05-20
- Trigger: Wiresheet apply after correcting type field
- Symptom/Error: `{"error":"Path not in allowlisted roots: station:|slot:/sandbox","allowedValues":[]}`
- Root Cause: Agent guessed `station:|slot:/sandbox` without first calling `nmcp.component.children` to discover valid roots. Server returns empty `allowedValues` so the agent had no self-correction data.
- Corrective Action: ALWAYS call `nmcp.component.children` with `ord='station:|slot:/'` before any write to discover the real tree. Never hardcode or assume slot paths.
- Reusable Payload or Prompt Pattern:
  ```
  Step 0 (mandatory): nmcp.component.children  ord=station:|slot:/
  → inspect results to find allowlisted parent
  → then build wiresheet operations using confirmed path
  ```
- Files Updated:
  - src/agent.py  (system prompt + _augment_path_error interceptor)
  - docs/agent-lessons.md

---

## 2026-05-21 - Link payload malformed (missing from/to, then out/out shorthand)

- Date: 2026-05-21
- Trigger: Wiring step for furnace and DX staging logic in mcpDemoAhu
- Symptom/Error:
  - `Missing required field: from`
  - `Missing required field: to`
  - `Path not in allowlisted roots: out/out`
- Root Cause: link operations were generated with incomplete or shorthand endpoints instead of absolute source/target endpoint strings.
- Corrective Action: enforce minimum link fields (`from`, `to`) and require absolute endpoint strings for both fields before plan/apply.
- Reusable Payload or Prompt Pattern:
  ```
  For each link operation:
  - type: link
  - from: absolute source endpoint under allowlisted root
  - to: absolute target endpoint under allowlisted root
  Never use shorthand tokens such as out, inA, or out/out.
  ```
- Files Updated:
  - src/agent.py (link validation + prompt hardening)
  - AGENTS.md
  - docs/niagara-agent-playbook.md
  - docs/agent-lessons.md

---

## 2026-05-21 - setSlot payload malformed (missing componentOrd during facet writes)

- Date: 2026-05-21
- Trigger: "Set the proper facets for all points" under `.../Drivers/sandbox/tstat`
- Symptom/Error:
  - `Missing required field: componentOrd`
- Root Cause: setSlot operations were generated without the required `componentOrd` field.
- Corrective Action: enforce setSlot minimum fields (`componentOrd`, `slot`, `value`) and require absolute `componentOrd` before plan/apply.
- Reusable Payload or Prompt Pattern:
  ```
  For each facet update operation:
  - type: setSlot
  - componentOrd: absolute ORD of target point
  - slot: facets
  - value: facet payload
  ```
- Files Updated:
  - src/agent.py (setSlot validation + prompt hardening)
  - AGENTS.md
  - docs/niagara-agent-playbook.md
  - docs/agent-lessons.md

---

## 2026-05-21 - Facet unit writes failed using nested slot facets.units

- Date: 2026-05-21
- Trigger: Setting temperature units to degree F under `.../Drivers/sandbox/tstat`
- Symptom/Error:
  - `no compatible runtime set method found for slot 'facets.units'`
- Root Cause: attempted nested facet sub-slot write; server expects writing the full `facets` slot value.
- Corrective Action: block nested `facets.*` setSlot payloads and require `slot=facets` with a full value.
- Reusable Payload or Prompt Pattern:
  ```
  For facet updates:
  - type: setSlot
  - componentOrd: absolute ORD of target point
  - slot: facets
  - value: full facets value (includes units/precision/etc.)
  ```
- Files Updated:
  - src/agent.py (block facets.* nested slot writes)
  - AGENTS.md
  - docs/niagara-agent-playbook.md
  - docs/agent-lessons.md
