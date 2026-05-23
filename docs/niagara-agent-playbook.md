# Niagara Agent Playbook

This playbook stores proven command patterns and payload templates for the nMCP workflow.

## 1. Preflight Checklist

1. Confirm connected state.
2. Confirm target ORD is allowlisted.
3. Confirm required source components exist.
4. Use the smallest valid payload first.

## 2. Canonical Wiresheet Templates

### 2.1 Create BooleanWritable point

{
  "rootOrd": "station:|slot:/Drivers/sandbox",
  "operations": [
    {
      "type": "createComponent",
      "parentOrd": "station:|slot:/Drivers/sandbox",
      "name": "ExFanReq",
      "componentType": "control:BooleanWritable"
    }
  ],
  "strict": true,
  "dryRun": true
}

### 2.2 Create multiple writable points

{
  "rootOrd": "station:|slot:/Drivers/sandbox",
  "operations": [
    {
      "type": "createComponent",
      "parentOrd": "station:|slot:/Drivers/sandbox",
      "name": "ExFanReq",
      "componentType": "control:BooleanWritable"
    },
    {
      "type": "createComponent",
      "parentOrd": "station:|slot:/Drivers/sandbox",
      "name": "ExFanCmd",
      "componentType": "control:BooleanWritable"
    },
    {
      "type": "createComponent",
      "parentOrd": "station:|slot:/Drivers/sandbox",
      "name": "ExFanStatus",
      "componentType": "control:BooleanWritable"
    }
  ],
  "strict": true,
  "dryRun": true
}

### 2.2a Create point with facets at creation time

{
  "rootOrd": "station:|slot:/Drivers/sandbox",
  "operations": [
    {
      "type": "createComponent",
      "parentOrd": "station:|slot:/Drivers/sandbox",
      "name": "SpaceTemp",
      "componentType": "control:NumericWritable",
      "facets": {
        "units": "degreesFahrenheit",
        "precision": 1,
        "min": 32,
        "max": 120
      }
    }
  ],
  "strict": true,
  "dryRun": true
}

Notes:
- Facets can be supplied on createComponent when the target component type supports it.
- Use the whole facets object rather than writing nested sub-slots later when possible.

### 2.3 Upgrade dry run to apply

Set dryRun to false only after plan validation succeeds.

### 2.3a Set slot template (facets or metadata)

{
  "rootOrd": "station:|slot:/Drivers/sandbox/tstat",
  "operations": [
    {
      "type": "setSlot",
      "componentOrd": "station:|slot:/Drivers/sandbox/tstat/SpaceTemp",
      "slot": "facets",
      "value": "<facet-value>"
    }
  ],
  "strict": true,
  "dryRun": true
}

Notes:
- setSlot requires componentOrd, slot, and value.
- componentOrd must be an absolute ORD under an allowlisted root.
- For facet updates, target each point individually with slot=facets.
- Do not use nested slot names like facets.units; write the full facets value to slot=facets.

### 2.4 Link operation template (absolute endpoints)

{
  "rootOrd": "station:|slot:/Drivers/sandbox/mcpDemoAhu",
  "operations": [
    {
      "type": "link",
      "from": "station:|slot:/Drivers/sandbox/mcpDemoAhu/FurnaceEnable|out",
      "to": "station:|slot:/Drivers/sandbox/mcpDemoAhu/FurnaceStage1Control|inA"
    }
  ],
  "strict": true,
  "dryRun": true
}

Notes:
- from and to must be absolute endpoint strings under an allowlisted root.
- Never use shorthand endpoint values like out, inA, or out/out.
- Discover endpoint names first before building link operations.

## 3. Recommended Execution Sequence

1. nmcp.component.children on candidate roots.
2. nmcp.component.search for prerequisite components.
3. nmcp.wiresheet.plan with strict true.
4. nmcp.wiresheet.apply.
5. nmcp.component.search and nmcp.wiresheet.links for verification.

## 4. Known Failure -> Fix Map

### Error: Validation failed: Operation at index N has unsupported type: null

Cause:
- operations item missing type.

Fix:
- Add type to every operation.
- Use one of: createComponent, setSlot, link, addCompositePin.

### Error: Path not in allowlisted roots

Cause:
- target ORD outside allowlist.

Fix:
- Enumerate children from known allowed roots.
- Re-target payload to an allowlisted ORD.

### Error: Missing required field: componentOrd (setSlot operations)

Cause:
- setSlot operation generated without componentOrd.

Fix:
- Include componentOrd, slot, and value on every setSlot operation.
- Use an absolute componentOrd under an allowlisted root.

### Error: no compatible runtime set method found for slot 'facets.units'

Cause:
- attempted to write a nested facet sub-slot instead of the facets slot.

Fix:
- use setSlot with slot=facets and a full facets value.
- do not use slot names like facets.units.

### Error: Missing required field: from/to (link operations)

Cause:
- link operations were generated without from or to fields.

Fix:
- Include both from and to for every link operation.
- Use absolute endpoint strings, not shorthand slot names.

### Error: Path not in allowlisted roots: out/out

Cause:
- shorthand token was used in link from/to instead of an absolute endpoint.

Fix:
- Discover source/target endpoints first.
- Use full absolute endpoint strings in from and to.

## 5. Prompting Pattern for Deterministic Writes

Use this planning instruction before mutation:

- Build operations with explicit type for every item.
- Validate with nmcp.wiresheet.plan strict true.
- If valid is false, do not apply.
- Explain correction, regenerate minimal payload, and revalidate.

## 6. Verification Pattern

After apply:

1. Confirm component existence by name and type.
2. Confirm slot values or links for logical behavior.
3. Report exact ORDs created or modified.

## 7. Change Log Policy

When a new failure pattern appears:

1. Add to docs/agent-lessons.md.
2. Add durable rule to AGENTS.md if broadly applicable.
3. Add canonical snippet here if it has reusable payload shape.
