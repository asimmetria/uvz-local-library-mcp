# Product flow

## Two roles

### 1. Knowledge maintainer

Maintainer has access to the workspace with internal repositories and runs one
command from its parent directory:

```text
library-knowledge-mcp build --workspace /path/to/projects
```

The command:

1. discovers configured Git roots and Gradle modules under the workspace;
2. safely updates each source to its configured branch (`master` by default)
   using `fetch` + `pull --ff-only`;
3. runs extraction, audit and retrieval evaluation;
4. generates `knowledge.db` and `generated-catalog.md` from the same commit
   set;
5. packages them as one versioned knowledge artifact;
6. publishes the artifact only to the approved internal repository or artifact
   storage.

A failed source, audit or evaluation prevents publishing a new artifact; the
previous version remains installable.

### 2. Developer

Developer does not need local clones of every library. They download the
`local-library-mcp` project and run:

```text
./install.sh
```

The installer:

1. creates/updates an isolated Python environment;
2. installs the local stdio MCP configuration without deleting other MCPs;
3. installs one generic skill and its generated catalog;
4. downloads or unpacks the latest approved `knowledge.db` locally;
5. runs a smoke test (`tools/list` and a known catalog entry).

The agent thereafter uses only local SQLite and local stdio. It does not need
an external MCP endpoint or access to all source repositories.

## Artifact contents

```text
knowledge-pack-<version>/
  knowledge.db
  generated-catalog.md
  manifest.json          # pack versions, commits, checksums, build time
  evaluation-summary.json
```

`manifest.json` makes answers traceable to a specific pack and commit set.

## Publishing rule

SQLite FTS stores text fragments from source files. It is therefore sensitive
source-derived data, not a harmless cache. Never publish it to a public Git
repository or personal storage. For frequent or large updates prefer an
internal artifact registry or Git LFS over ordinary Git blobs; the first small
internal prototype may use a private repository if its data policy permits it.
