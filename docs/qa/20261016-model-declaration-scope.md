# Official capability declarations are endpoint scoped

Issue #146; catalog revision 3. Checked 2026-10-16 against the primary
[DeepSeek API setup](https://api-docs.deepseek.com/) and
[vision documentation](https://api-docs.deepseek.com/guides/vision/).
Those pages document the `https://api.deepseek.com` OpenAI-compatible base and
`deepseek-flash`; the setup page explicitly retains the two legacy Flash IDs.

Previously selecting the `deepseek` provider label marked the Flash IDs as
officially vision capable even when the configured URL was a proxy or another
service. The declaration now applies only to the documented base (with an
optional trailing slash) and exact model IDs. Custom paths, proxies, lookalike
hosts, alternate protocols and arbitrary aliases remain unknown unless their
own endpoint/model image probe is still valid. A declaration remains distinct
from a successful probe and from semantic-quality validation.

No endpoint is contacted, credentials are changed, or task schema is migrated.
The planner's existing configured/declared/verified/unknown distinctions remain.
Six capability unit tests pass, including negative endpoint and alias cases and
the independently verified custom endpoint case. Full integrated checks are
recorded separately after the final combined tree is tested.

This fixes declaration attribution; live text/vision/ASR compatibility, quality,
billing and latency remain unmeasured. No new image-count, context or cost limit
is inferred from this declaration, and #146 remains open.
