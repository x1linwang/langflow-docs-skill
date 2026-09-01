# Getting third-party Python packages into Langflow

The official page is `/install-custom-dependencies`. Also relevant:
`/develop-application` for containerising, and `/deployment-docker`.

**This skill does not document third-party packages.** For how to *use*
`pandas`, `scipy`, `yfinance`, `httpx` or anything else on PyPI, use Context7 or
the package's own documentation. This file only covers getting them installed
where a Langflow component can import them, and the Langflow-specific traps in
doing so.

## Docker: bake them into the image

The reliable pattern is a small Dockerfile on top of a pinned Langflow tag,
rather than installing at container start.

```dockerfile
FROM langflowai/langflow:1.11.4

USER root
RUN pip install --no-cache-dir "edgartools==5.53.0" "yfinance>=1.5.1" "scipy" \
 && python -c "import edgar, yfinance, scipy"   # fail the build, not the flow

RUN mkdir -p /app/custom_components && chown -R 1000:1000 /app/custom_components
USER 1000

CMD ["langflow", "run", "--host", "0.0.0.0", "--port", "7860"]
```

Why each part matters:

- **Pin the Langflow tag.** `latest` will move you across a minor version and
  change component names under you.
- **Import-check in the same `RUN`.** A package that installs but cannot import
  otherwise surfaces as a mystery `NameError` inside a component at flow-build
  time, which is a much worse place to discover it.
- **`USER root` then back to `1000`.** The Langflow image runs as uid 1000.
  Anything you create as root must be chowned back, or the app cannot write to
  it.
- **Installing at container start instead** works but re-downloads on every
  restart and turns a dependency problem into a runtime problem.

## Version claims in upstream package docs

Worth knowing because it has burned real time: a package's documentation site
sometimes documents a version that is not on PyPI yet. `pip install` then fails
outright, or installs something whose API does not match what you just read.
Check the installed version rather than trusting the docs page:

```bash
docker compose run --rm --no-deps -T --entrypoint /app/.venv/bin/python langflow \
  -c "import edgar; print(edgar.__version__)"
```

Note the entrypoint: the Langflow image has its own virtualenv at
`/app/.venv`, so plain `python` may not be the interpreter that matters.

## Importing them from a component

Module-level imports must be flat and unconditional, because Langflow loads
component files by AST surgery — see `custom-components.md`, section 1. For a
heavy dependency, import it inside the method that needs it:

```python
from lfx.custom import Component          # flat, top level

class MyComponent(Component):
    def compute(self):
        from scipy import stats            # call time, fine
```

That keeps component load fast and avoids paying for an import in flows that
never call the action.

## Verifying before touching the UI

Much faster than clicking through the editor:

```bash
docker compose run --rm --no-deps -T --entrypoint /app/.venv/bin/python langflow \
  - < tests/smoke_test.py
```

Stub `lfx` in unit tests so they run without Langflow at all, and keep one live
smoke test that runs inside the real image. A component that imports cleanly in
your host Python but not in the image is the common failure, and only the
in-image run catches it.

## If an import still fails at flow-build time

1. Is the package in the *image*, not just on your host?
2. Is it importable by `/app/.venv/bin/python` specifically?
3. Is the failing import at module level, and is it flat? No `try/except`, no
   `TYPE_CHECKING`, no `importlib`.
4. Is it a sibling-module import? Those do not resolve; inline the helper.
5. Was the container restarted after the image changed?

See also `/install-custom-dependencies` and `/troubleshoot`.
