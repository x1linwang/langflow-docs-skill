# Writing custom components for Langflow 1.11.x

The official page is `/components-custom-components`. Read it for the
`Component` class, `inputs`, `outputs`, and `build_config`. This file covers
the rules that page does not state, which is where most custom components
actually break.

**Provenance:** sections 1, 2, 4 and 5 are empirical — verified against a
running Langflow 1.11.4 container and its source, not quotes from the docs.
Section 3 is documented, and says where. Where a rule depends on internal
module paths, those paths are named so you can re-check them in the version you
are running. Treat the empirical parts as "true in 1.11.x, verify if you
upgrade".

## Contents

1. Langflow does not import your file — it performs AST surgery
2. How a component becomes agent tools (names, descriptions, schema)
3. Which input types support tool mode
4. Category discovery and `__init__.py`
5. Field names: the docs are not authoritative, the registry is
6. Checklist

## 1. Langflow does not import your file — it performs AST surgery

`lfx/custom/validate.py::prepare_global_scope` walks your module's AST,
executes **only the top-level `ast.Import` and `ast.ImportFrom` nodes**, and
then `exec`s the class definition against the resulting scope.

The consequence is narrow and severe: **every import your class body needs must
be a flat, unconditional, top-level statement.**

```python
# WORKS - flat, top-level, unconditional
from lfx.custom import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.message import Message
```

```python
# BREAKS - this is an ast.Try node, not an ast.ImportFrom, so Langflow
# never executes it, and the class body dies with:
#   NameError: name 'Component' is not defined
try:
    from lfx.custom import Component
except ImportError:
    Component = object

# BREAKS for the same reason - ast.If, not ast.ImportFrom
if TYPE_CHECKING:
    from lfx.schema.message import Message

# BREAKS - importlib is a call, not an import node
Component = importlib.import_module("lfx.custom").Component
```

**A function-body import is fine.** Only *module-level* imports need to be
flat, because a function body is not executed at load time — it runs when the
method is called, by which point normal import machinery applies. This is the
escape hatch for a heavy or optional dependency:

```python
from lfx.custom import Component          # top level, flat

class MyComponent(Component):
    def compute(self) -> Message:
        from scipy import stats            # runs at call time, perfectly OK
        ...
```

**Sibling imports do not work.** Langflow loads each component file
standalone, so `from .helpers import to_float` is not reliably resolvable and
fails with a bare `NameError` at build time. Duplicate the small helper into
each file. It feels wrong and it is still the right call.

## 2. How a component becomes agent tools

Langflow builds tools in `lfx/base/tools/component_tool.py`, in
`ComponentToolkit.get_tools()`. Three rules follow from it, and each one is a
common bug when unknown.

### The tool name is the output's method name

Not the display name, not the class name. The method name is slugified with:

```python
re.sub(r"[^a-zA-Z0-9_-]", "-", name)
```

So name your methods as the slug you want the model to see. A method called
`company_credit_risk` becomes the tool `company_credit_risk`; renaming
`display_name` changes nothing the model sees.

### The tool description is `Output(info=...)`

It falls back to the component's `description` when `info` is unset. A
component with twelve outputs and no `info` therefore gives the agent twelve
tools with one identical description — the single most common reason an agent
picks the wrong action. Set `info` on every `Output`.

```python
outputs = [
    Output(
        name="credit_risk",
        display_name="Credit risk",
        method="company_credit_risk",     # <- this is the tool name
        info="Altman Z-score and Piotroski F-score for one ticker. "
             "Reads `ticker`. Ignores `num_periods`.",   # <- this is the description
    ),
]
```

### The args schema is built once and shared by every action

There is no per-action schema. Langflow collects **every input marked
`tool_mode=True`** into a single schema shared by all of that component's
tools. Two practical consequences:

- Keep the tool-mode input set small and generic. An input only one action
  needs still appears in every action's signature.
- Say in each input's `info` which actions read it and which ignore it, because
  the model sees the union and cannot tell otherwise.

**This is also the main context cost of a component.** Every tool description
is re-sent on every agent turn. One component exposing 34 actions measured at
~75,600 characters — roughly 18,900 tokens — of tool definitions per turn.
Splitting one large component into several narrower ones, each behind a
sub-agent in tool mode, is the standard fix. See `/agents-tools` for
agent-as-a-tool wiring.

## 3. Which input types support tool mode

**This one is documented** — see `/agents-tools#make-any-component-a-tool`,
which lists exactly these six for 1.11.x:

`DataInput`, `DataFrameInput`, `PromptInput`, `MessageTextInput`,
`MultilineInput`, `DropdownInput`.

It is repeated here because it is easy to miss: the list lives on the agents
page, not on the custom-components page where you are when you hit the problem.

Notably **`IntInput` and `BoolInput` do not**. If an action needs a number from
the model, take a `MessageTextInput` and parse it yourself. This is why you see
string-typed period counts in components that look like they should use
`IntInput`.

`DropdownInput` options become a `Literal[...]` enum in the tool schema when
there are 50 or fewer options. So wherever the value set is closed, a dropdown
is strictly better than free text — the model gets a constrained choice instead
of a chance to invent a value.

Returning `Message` from an action is the safe default: in tool mode Langflow
unwraps it to plain text, so you control the exact shape and token budget of
what the agent reads.

## 4. Category discovery and `__init__.py`

`LANGFLOW_COMPONENTS_PATH` points at a directory of *category* directories, not
at component files:

```
$LANGFLOW_COMPONENTS_PATH/
└── finance/                 <- becomes the category heading in the menu
    ├── __init__.py          <- required
    └── my_component.py
```

The folder name becomes the category heading in the Components menu. **Without
`__init__.py` the components silently never appear** — no error, no log line,
just absence. The `__init__.py` should import and `__all__`-export the classes.

If a component is missing from the menu, check in this order: `__init__.py`
exists; the path is mounted where `LANGFLOW_COMPONENTS_PATH` says; the file's
imports are all flat; the container was restarted. See
`/components-custom-components#custom-component-path`.

## 5. Field names: the docs are not authoritative, the registry is

Documentation lags code. For the exact input names, types, and handle names of
a component as it exists in **your** running instance, query the registry:

```bash
curl -s http://localhost:7860/api/v1/all | jq 'keys'
```

Use it whenever you are writing flow JSON by hand, matching parameter names, or
wondering whether a field was renamed. The docs tell you how tool mode works;
the registry tells you what this component's field is actually called.

## 6. Checklist

Before assuming a component is broken:

- [ ] Every module-level import flat, unconditional, top level?
- [ ] No `TYPE_CHECKING`, no `try/except ImportError`, no `importlib`?
- [ ] No sibling-module imports?
- [ ] `__init__.py` present in the category directory?
- [ ] Every `Output` has a distinct `info`?
- [ ] Method names read as the tool names you want?
- [ ] Every `tool_mode=True` input documented as to which actions use it?
- [ ] Tool-mode inputs limited to the six supported types?
- [ ] Heavy dependencies imported inside methods, and installed in the image?
      See `external-packages.md`.
