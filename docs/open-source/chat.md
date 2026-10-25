# AI (SI) Chat modes

AI (SI) Chat uses the selected local model through the existing Google ADK root agent and the
provider-neutral `LLMProvider`. The composer selects the response policy for one submitted turn:

- **Wiki** is the default. Organization-specific questions and referential follow-ups can use the
  existing owner-authorized Wiki, source, relationship, graph, dataset, and guarded public-search
  tools. General conversation and the bounded deterministic arithmetic path do not force Wiki
  retrieval.
- **Direct** uses the same local model path with no retrieval tools. The server withholds Wiki,
  source, relationship, graph, dataset, and public-web tool declarations for that ADK invocation;
  the provider adapter also drops tool schemas as a defense in depth. Direct never falls back to
  Wiki or public search, even when the prompt asks it to do so or the runtime was launched with
  `--yes-web-search`.

Direct can continue from visible user and assistant messages. Knemora does not persist ADK tool
responses in conversation history, so fresh Direct invocations do not replay prior Wiki excerpts,
source payloads, dataset rows, or web results as tool evidence. A previous assistant answer may
already contain a summary or citation from an earlier Wiki turn; Direct treats that text only as
conversation context, not as newly verified evidence. Switch to Wiki to re-check it.

The selector remains stable while the current conversation stays open. Starting a conversation
with the **New conversation** action, opening another conversation, or reloading the page resets it
to Wiki. Legacy clients and requests that omit the field also use Wiki. The selected value is
captured when Send is activated and the selector is disabled until that response ends, so UI
changes cannot alter an in-flight request. Historical messages are not rewritten or relabelled,
and response mode is not stored as a second conversation authority.

Direct displays **Generating answer…** rather than Wiki search/source progress. Wiki keeps the
existing progress labels. Both modes preserve native-role history, response-language matching,
explicit language overrides, context fitting, SSE event names, cancellation, error reporting,
owner isolation, and deterministic arithmetic behavior.

## API

Both existing message endpoints accept the same additive field:

```json
{
  "content": "Explain this concept simply.",
  "response_mode": "direct"
}
```

`response_mode` accepts only `"wiki"` or `"direct"`. Omission defaults to `"wiki"`; any other
value returns the existing typed HTTP 422 validation response. Clients cannot provide tool names
or override server tool policy. The endpoints and SSE events are unchanged:

```text
POST /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/messages/stream
```

## Privacy boundaries

Both modes keep ordinary inference local through the active llama.cpp model. Wiki may access
owner-authorized local knowledge and may use public search only when the operator enabled it and
the current Wiki-mode prompt explicitly opts in. Direct performs no local-knowledge or public-web
retrieval. Neither mode writes chat text or answers into the Wiki, graph, sources, or datasets.
