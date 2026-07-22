---
name: library-knowledge-workflow
description: "Use for questions about internal libraries, facades, shared models, adapters, platform dependencies, configuration, standards, Jimmer, or existing project patterns. Requires local-library-mcp search before asserting API details."
---

# Library Knowledge Workflow

1. Call `mcp__local-library-mcp__list_libraries` if the relevant library is
   unclear. Call `list_repositories` if the question concerns an application
   or if its repository name is unclear.
2. Call `mcp__local-library-mcp__search_knowledge` before proposing an API,
   dependency, configuration key or integration pattern.
3. Call `get_source` for the strongest result when code accuracy matters.
4. State the source id and commit in the answer. Do not invent API details when
   the local index has no supporting result.
5. For configuration questions, first call `search_config` to identify the
   source files and configuration set. If the user asks for an actual resulting
   value, call `resolve_config` with application, configuration_set and the
   relevant profile/module. Do not claim an effective value without its
   provenance and the reported merge order.
