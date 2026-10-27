# Workspace lists and conversation history

Workspace browsing uses bounded server-side lists. Documents and Ingestion show 10 records per
page, Knowledge shows 8, and the Available datasets panel shows 5. Overview requests only the five
newest active sources. Search and filters are applied before authorized counts and pagination, and
the shared pager displays fixed groups of at most five numbered pages with one-page **Prev** and
**Next** navigation.

AI (SI) Chat keeps the eight most recently active conversations in its aside. **View all** opens the
authenticated `/chat/conversations` history table with server-side title search and 15 records per
page. Conversation titles can be renamed inline; otherwise the first persisted user prompt provides
a deterministic title without an external model call.

Persisted timestamps are stored as unambiguous UTC instants and rendered in the browser timezone. A
date separator appears only after a persisted assistant response establishes that response's local
calendar day, so an optimistic prompt never creates an empty or premature day group.
