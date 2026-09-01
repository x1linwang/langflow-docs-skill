# Which credential works on which Langflow route

The authoritative doc pages are `/api-keys-and-authentication`,
`/authentication-overview`, and `/api-reference-api-examples`. Read them first.
This file exists because the *practical* answer — "I got a 401, what now" — is
spread across those pages plus the environment-variable reference.

**Provenance:** empirical, against Langflow 1.11.4 with `LANGFLOW_AUTO_LOGIN=true`.
Confirm against `/api-keys-and-authentication` for your configuration.

## The short version

There are two credentials and they are not interchangeable.

| Credential | Header | Works on |
|---|---|---|
| API key | `x-api-key: <key>` | flow execution — `/api/v1/run/...`, webhooks |
| Session JWT | `Authorization: Bearer <token>` | most management routes — flows, files, projects, monitor, `/api/v1/all` |

A 401 or 403 on a management route while your `x-api-key` works fine on `/run`
is the normal symptom of using the wrong one, not of a bad key.

## With `LANGFLOW_AUTO_LOGIN=true`

Auto-login is the usual local/course setup. It skips the login screen, but the
management API still expects a token. Obtain one by calling the auto-login
endpoint and reusing the JWT it returns:

```bash
BASE=http://localhost:7860
TOKEN=$(curl -s "$BASE/api/v1/auto_login" | jq -r .access_token)

# Management route: JWT
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/all" | jq 'keys | length'

# Execution route: API key
curl -s -X POST "$BASE/api/v1/run/$FLOW_ID" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $LANGFLOW_API_KEY" \
  -d '{"input_value":"hello","input_type":"chat","output_type":"chat"}'
```

Auto-login also affects where the File System tool writes: paths resolve under
`LANGFLOW_FS_TOOL_BASE_DIR`, and the per-user segment differs between an
auto-login user and a real one. If a flow cannot find a file it wrote earlier,
check that first. See `/file-system` and `/environment-variables`.

## `GET /api/v1/all` is the component registry

This endpoint returns every component the running instance knows about,
including custom ones, with each component's full template. It is the ground
truth for:

- exact input names and types
- handle names and `input_types` for building edges
- whether a component exists in this version at all

Use it whenever documentation and reality might have diverged — which is
whenever you are writing flow JSON, or debugging a field name.

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/all" \
  | jq '.finance | keys'                      # custom category
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/all" \
  | jq '.agents.Agent.template | keys'        # one component's fields
```

## Running a flow

Full details, with curl/Python/JavaScript examples, are on `/api-flows-run`.
Those examples are searchable in this skill — the code bodies are inlined into
the index, so `search "run flow python example"` returns actual code.

The essentials:

- `POST /api/v1/run/<flow-id-or-endpoint-name>`
- `input_type` / `output_type` are usually `"chat"`
- `session_id` is what threads messages together; see `/session-id`
- `stream=true` as a query parameter for token streaming
- global variables can be passed in request headers — see `/api-flows-run`

## MCP

Langflow can act as an MCP server, exposing a project's flows as tools:

```
http://localhost:7860/api/v1/mcp/project/<project-id>/streamable
```

authenticated with `x-api-key`. See `/mcp-server`. For Langflow consuming
external MCP servers, see `/mcp-client` and `/mcp-tools`.

## Debugging a 401 or 403

1. Is it a management route or an execution route? Match the credential to the
   table above.
2. Is `LANGFLOW_AUTO_LOGIN` what you think it is? It changes the whole auth
   posture.
3. Is the key scoped to the right user? Keys are per-user.
4. Check `/api-keys-and-authentication#ssrf-protection` if the failure is an
   outbound request from the API Request component rather than an inbound call.
5. `search "api key" --path Develop` for the current environment variables.
