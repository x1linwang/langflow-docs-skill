# Flow JSON structure in Langflow 1.11.x

For the user-facing side of importing and exporting, see
`/concepts-flows-import`. This file documents the on-disk shape, which the docs
do not, so that a flow can be generated or patched programmatically.

**Provenance:** empirical, from flows exported by Langflow 1.11.4. The schema is
not a public contract — verify against a fresh export after upgrading.

## Top level

```json
{
  "name": "My flow",
  "description": "...",
  "data": { "nodes": [...], "edges": [...], "viewport": {...} },
  "is_component": false,
  "endpoint_name": null,
  "webhook": false,
  "mcp_enabled": null,
  "access_type": "PRIVATE",
  "tags": [],
  "locked": false,
  "id": "...", "user_id": "...", "folder_id": "..."
}
```

Everything that matters is under `data`. `endpoint_name` is what lets you call
the flow by a readable name instead of a UUID; see `/concepts-publish`.

## Nodes

```json
{
  "id": "Agent-b",
  "type": "genericNode",
  "position": {"x": 0, "y": 0},
  "measured": {"width": 320, "height": 500},
  "data": {
    "id": "Agent-b",
    "type": "Agent",
    "node": {
      "template": { "...one entry per input, keyed by input name..." },
      "outputs": [ ... ],
      "base_classes": [], "output_types": [], "field_order": [],
      "display_name": "Agent", "description": "...", "icon": "bot",
      "tool_mode": false, "frozen": false, "legacy": false
    }
  }
}
```

Two details that trip people up:

- **`node.type` is almost always the literal string `genericNode`.** The thing
  that identifies the component is `node.data.type`.
- **`node.id` and `node.data.id` must match**, and edges reference that id.

### Custom component nodes

A component loaded from `LANGFLOW_COMPONENTS_PATH` gets a namespaced
`data.type`:

```
ext:<category-directory>:<ClassName>@extra
```

For example `ext:finance:SECEdgarResearch@extra` — `finance` being the category
directory name, `SECEdgarResearch` the class name. Built-in components use a
bare name like `Agent` or `ChatOutput`.

### `template`

One entry per input, keyed by the **input's `name`**, plus `_type` and `code`
(the component's source, for custom components). This is exactly why you should
build nodes from `GET /api/v1/all` rather than by hand: that endpoint returns
the live registry with the correct template for every component, and the field
names there are authoritative in a way the docs are not.

## Edges — the encoded handle gotcha

This is the single most confusing part of the format. Each edge carries its
handles **twice**: once as parsed objects under `data`, and once as strings in
`sourceHandle` / `targetHandle`.

```json
{
  "source": "ChatInput-b",
  "target": "Agent-b",
  "sourceHandle": "{œdataTypeœ: œChatInputœ, œidœ: œChatInput-bœ, œnameœ: œmessageœ, œoutput_typesœ: [œMessageœ]}",
  "targetHandle": "{œfieldNameœ: œinput_valueœ, œidœ: œAgent-bœ, œinputTypesœ: [œMessageœ], œtypeœ: œstrœ}",
  "data": {
    "sourceHandle": {"dataType": "ChatInput", "id": "ChatInput-b",
                     "name": "message", "output_types": ["Message"]},
    "targetHandle": {"fieldName": "input_value", "id": "Agent-b",
                     "inputTypes": ["Message"], "type": "str"}
  },
  "id": "reactflow__edge-ChatInput-b{œdataTypeœ:...}-Agent-b{œfieldNameœ:...}",
  "animated": false,
  "className": ""
}
```

**Every `"` in the stringified handle is replaced by `œ` (U+0153, LATIN SMALL
LIGATURE OE).** `/concepts-flows-import` shows this in an example flow but never
says what the character is or why it is there, which is why it reads like file
corruption the first time you meet it. React Flow uses the handle string inside DOM ids and CSS
selectors, where a double quote would break things, so Langflow substitutes a
character that will not appear in real data.

To build an edge programmatically:

1. Construct the handle dicts.
2. `json.dumps(...)` them, then replace `"` with `œ`, for `sourceHandle` and
   `targetHandle`.
3. Put the unmodified dicts under `data.sourceHandle` / `data.targetHandle`.
4. Set `id` to `reactflow__edge-<source><sourceHandleString>-<target><targetHandleString>`.

If the two representations disagree, or the encoding is wrong, the flow will
usually load in the editor with the edge silently missing.

```python
def encode_handle(handle: dict) -> str:
    return json.dumps(handle, separators=(", ", ": ")).replace('"', "œ")
```

Note the source handle keys are `dataType`, `id`, `name`, `output_types`, while
the target handle keys are `fieldName`, `id`, `inputTypes`, `type`. They are not
symmetric.

## Tool mode in a saved flow

A component wired into an agent's tools port has, in its node:

- `node.tool_mode: true`
- an output named `component_as_tool` whose `method` is `to_toolkit` and whose
  `types` is `["Tool"]`
- a `tools_metadata` entry in `template`, listing the individual actions

The reliable way to produce this is not to write it by hand: set it in the UI
and export, or call the `custom_component/update` endpoint, which returns the
updated node with tool mode applied. Hand-writing `tools_metadata` is how flows
end up with actions the agent cannot call.

For wiring an agent as another agent's tool — Toolset output into the parent's
Tools port — see `/agents-tools#use-an-agent-as-a-tool`.

## Practical advice

Generating a flow from scratch is more fragile than it looks. The durable
workflow is:

1. Build the skeleton once in the visual editor, export it.
2. Patch the exported JSON programmatically for the parts that vary.
3. Re-import and open it once in the editor to confirm every edge survived.

Fetch node templates from `GET /api/v1/all` rather than copying them between
flows, so that field names track the running version.
