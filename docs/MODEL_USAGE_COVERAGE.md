# Local model usage coverage

`GET /api/model/usage` reports the provider-returned counts recorded by this
LearnNote backend. It does not report an account balance, invoice, spending cap,
monetary estimate, remote ASR usage, other applications, or every SDK transport
retry. A failed or rejected result may still consume tokens; its reported counts
remain in the ledger. An absent count is not evidence of free processing.

## Report schema 2

The response adds `schema_version: 2`. Existing top-level `totals`, `recent`,
`models`, and `daily` arrays/objects and the `requests` / `measured_requests`
fields remain. The SQLite schema and saved request rows are unchanged.

Each total, model group and UTC day includes:

| Value | Requests that reported that value |
| --- | --- |
| `input_tokens` | `measured_input_requests` |
| `output_tokens` | `measured_output_requests` |
| `total_tokens` | `measured_requests` |

A value is the sum of the non-null provider-reported values in that group. For a
nonempty group, no reported values produces JSON `null`, not zero. A sum of zero
with positive coverage is an actual reported zero. The empty overall ledger has
zero requests, zero coverage and zero sums; it has no daily/model rows.

Coverage is independent for each field. A provider may report only a total, or
only components. LearnNote does not subtract or add fields to reconstruct a
missing provider count. `requests` includes unknown and failed recorded requests.
`measured_requests` means total-token coverage, not coverage of every component.
Daily groups include the existing 14-day UTC window; totals/model groups retain
older history. Recent requests retain their original nullable fields and status.

## Consumer compatibility

In the previous response, aggregate `COALESCE(SUM(...), 0)` converted wholly
unknown groups to zero. Consumers must now accept null and inspect the matching
coverage field before presenting a sum as complete. In particular,
`Number(null)` must not be used to format token counts.

The bundled settings and profile distinguish:

- No requests: 0, with “尚无请求记录”.
- Requests without a reported count: “未知”, with coverage such as 0 / 2.
- Partial coverage: “已记录 25”, with coverage such as 1 / 2. Remaining usage and
  monetary cost are unknown.
- Complete recorded coverage: the reported sum, with matching coverage. This
  still applies only to the local recorded requests, not the provider account.

Daily meters display only known recorded values. An entirely unknown day has a
text placeholder, with no zero-valued meter. Partial meters and model rows expose
their coverage. Older responses without component coverage remain unknown for
those components; the UI does not borrow total coverage.

No historical rows are rewritten, replayed or backfilled. File-based backup or
export copies of the existing SQLite ledger retain their original bytes; reading
the report does not migrate the database. There is no standalone usage export
format in this change, and generated note exports do not consume this report.

## Validation scope

Synthetic temporary ledgers cover empty, unknown, true zero, partial fields,
failed requests, per-model/per-day grouping and old-record preservation. The
local API test uses the production router with an in-process ASGI client. The
Edge acceptance fixture exercises the shipped settings and profile with clearly
synthetic API responses, including error/refresh recovery, close/reopen, light
and dark themes, and desktop/narrow layouts. Neither establishes live model
quality or provider billing accuracy. #146 remains open.
