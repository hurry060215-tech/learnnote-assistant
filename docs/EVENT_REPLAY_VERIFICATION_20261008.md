# Event replay follow-through

Issue #151 remains open for incremental provider sections and longer network
soak evidence. This repair addresses a reproducible loss in terminal replay.

Previously a completed task with more than 2,000 pending event records emitted
one page and then the terminal marker. Events after that page were silently
lost to a reconnecting client. The server now drains full pages before checking
terminal status. The durable reader counts valid records while preserving
absolute file-line IDs, so a malformed/partial historical line cannot hide a
later valid page.

The real FastAPI streaming response regression creates 4,505 journal lines,
including three invalid lines, reconnects after ID900, and verifies every
remaining valid ID appears once in order before one terminal marker at4505.
Separate fresh Python processes read the same persisted cursor to verify that
no in-memory counter is needed across backend restart. Existing cursor/header,
Chinese JSON, safe event-name and terminal tests remain passing.

This is deterministic terminal replay and process-restart proof, not a claim
of hours of live provider streaming or a browser visual soak. No model,
credential, external service or user data is used.
