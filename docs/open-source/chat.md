# AI (SI) Chat modes

AI (SI) Chat uses the selected local model through the existing Google ADK root agent and the
provider-neutral `LLMProvider`. The composer selects the response policy for one submitted turn:

- **Wiki** is the default. Organization-specific questions and referential follow-ups can use the
  existing owner-authorized Wiki, source, relationship, graph, and dataset tools. General
  conversation and the bounded deterministic arithmetic path do not force Wiki retrieval. Wiki
  has no public-search tool or authority, under any runtime configuration.
- **Direct** uses the same local model path with no private retrieval tools. The server withholds
  Wiki, source, relationship, graph, and dataset declarations; the provider adapter also drops
  tool schemas as a defense in depth. Direct may perform the separate public-search step when its
  resolved request-level Web policy is enabled.

Direct can continue from visible user and assistant messages. Knemora does not persist ADK tool
responses in conversation history, so fresh Direct invocations do not replay prior Wiki excerpts,
source payloads, dataset rows, or web results as tool evidence. A previous assistant answer may
already contain a summary or citation from an earlier Wiki turn; Direct treats that text only as
conversation context, not as newly verified evidence. Switch to Wiki to re-check it.

The selector remains stable while the current conversation stays open. Starting a conversation
with the **New conversation** action, opening another conversation, or reloading the page resets it
to Wiki. Legacy clients and requests that omit the field also use Wiki. The selected value is
captured when Send is activated and the selector is disabled until that response ends, so UI
changes cannot alter an in-flight request. Historical messages are not rewritten. The server
stores execution metadata on each new assistant message in the existing message metadata field;
legacy messages truthfully omit unavailable attributes.

Direct displays **Generating answer…** rather than Wiki search/source progress. Wiki keeps the
existing progress labels. Both modes preserve native-role history, response-language matching,
explicit language overrides, context fitting, SSE event names, cancellation, error reporting,
owner isolation, and deterministic arithmetic behavior.

## Fast, Deep, and response metadata

**Fast** requests thinking off and **Deep** requests thinking on for every model call in that one
isolated ADK turn. The selected override remains active for later messages in the current browser
session. The provider sends the request-scoped value through llama.cpp's
`chat_template_kwargs.enable_thinking` only when the selected model template is registered as
controllable. The curated Qwen3 8B and Gemma 4 E4B templates are verified controllable and expose
both modes. Fixed-off models expose Fast only; custom or otherwise unverified models expose no
labelled override. Unsupported explicit requests return HTTP 422 and never silently claim a mode.
Fast does not mean that a model performs no internal computation, and Deep is not a quality
guarantee. Neither option changes context size, reloads the model, changes `.env`, or affects the
independent KnowledgeProposal v1 compilation configuration.

When `KNEMORA_LLM_ENABLE_THINKING` is absent, the startup default is Fast. The UI initializes from
the read-only capabilities response, retains a supported choice while the chat view is mounted,
and returns to the effective startup default after a page reload or backend restart. Assistant message metadata
records the actual response mode and provider model ID, configured display name/revision, effective
thinking mode/capability, and Web requested/attempted/succeeded/outcome fields. The footer renders
the server-confirmed model first; it never derives historical badges from current controls.

## Direct-only public web search

`KNEMORA_WEB_SEARCH_ENABLED` is the startup default for the **Web** control, not an operator lock.
Direct may turn Web ON or OFF without a launcher flag or restart. That temporary preference is
retained across messages and conversation navigation in the mounted chat view. Wiki always shows
Web OFF without erasing the remembered Direct preference. A page reload or changed backend runtime
identity reinitializes both controls from the newly read `.env` defaults. A Wiki request with
`web_search=true` returns HTTP 422 before persistence, inference, or any external call.

An accepted Direct+Web message causes one bounded DDGS/DuckDuckGo attempt before model synthesis;
the model is not given an autonomous search tool. The query is derived only from the current
message and is rejected if it includes an email address, URL, UUID, credential-like shape, or asks
to use private documents, Wiki content, history, or a prior answer. This is a conservative
restriction, not a perfect sensitivity classifier. Prior messages and private tool output are
never serialized to the search backend. Returned titles/snippets are bounded untrusted data, not
instructions or Wiki evidence. The UI and stored metadata distinguish success, no results, and
errors; raw result text is not persisted as execution metadata.

## API

Both existing message endpoints accept the same additive field:

```json
{
  "content": "Explain this concept simply.",
  "response_mode": "direct",
  "thinking_mode": "fast",
  "web_search": false
}
```

`response_mode` accepts `"wiki"` or `"direct"`; omission defaults to Wiki. `thinking_mode` accepts
`"fast"` or `"deep"`; omission uses the effective startup default when enforceable. In Direct,
omitting `web_search` uses the effective startup default; an explicit boolean overrides it for that
request. Wiki always resolves omission to false. Invalid combinations or unsupported thinking modes return HTTP 422. Clients
cannot provide tool names or override server policy. The existing endpoints remain:

```text
POST /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/messages/stream
GET  /api/v1/chat/capabilities
```

## Privacy boundaries

Both modes keep ordinary inference local through the active llama.cpp model. Wiki may access only
owner-authorized local knowledge and can never use public search. Direct performs no local-
knowledge retrieval; each optional public search sends only the restricted current-message
query. Neither mode writes chat text or answers into the Wiki, graph, sources, or datasets.

Persisted event times are generated from the host clock as timezone-aware UTC and serialized with
an offset. The browser converts them to its local timezone, including DST. Legacy timestamps that
lack an offset are interpreted as UTC for compatibility; if an old producer actually stored local
wall time without an offset, its original zone is irrecoverably ambiguous. Date separators are
derived from persisted assistant response days, never stored as message rows.
