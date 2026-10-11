# Third-Party Notices

Knemora's own source is licensed under the MIT License. Dependencies and external components retain
their own licenses. This summary is informational and does not replace the license files distributed
by each project.

## Runtime dependencies audited from the lockfiles

| Component | License |
| --- | --- |
| Alembic, FastAPI, openpyxl, Polars, Pydantic Settings, python-docx, PyYAML, SQLAlchemy | MIT |
| HTTPX, pypdf, Uvicorn | BSD-3-Clause |
| Google Agent Development Kit | Apache-2.0 |
| DDGS | MIT |
| psycopg | LGPL-3.0-only |
| python-multipart | Apache-2.0 |
| Vue, Vue Router, Pinia, VueUse, Marked | MIT |
| Sigma.js 3.0.3, Graphology 0.26.0, graphology-layout-forceatlas2 0.10.1 | MIT |
| Lucide | ISC |
| DOMPurify | MPL-2.0 OR Apache-2.0 |

Transitive and development dependencies are recorded in `apps/api/uv.lock` and
`apps/web/package-lock.json` and remain subject to their respective terms. Binary/source
distributions must preserve license texts and notices required by those dependencies.

## Integrations and models

- Knemora setup downloads the pinned official llama.cpp b11146 binary archive into the application
  home. llama.cpp and its packaged ggml/Metal/shared-library components are governed by their
  upstream MIT license; the complete payload and upstream `LICENSE` are preserved with the install.
- Knemora setup downloads pinned uv 0.11.22 and uses it to install a managed CPython 3.13.14
  distribution. uv is dual-licensed Apache-2.0 OR MIT. CPython is governed by the Python Software
  Foundation License; its distribution license/notices remain in the managed Python tree.
- Node.js and npm are user-installed prerequisites and retain their upstream licenses. Knemora does
  not redistribute or install Node.js.
- No GGUF or Qwen model weights are bundled. Operators must review and comply with the license and
  acceptable-use terms of the exact model they obtain.
- Optional external Markdown viewers are not bundled or installed by Knemora and remain under
  their own terms.
- The default ISTA-DASLab Qwen3-8B GSQ Q3_K_M GGUF, and the optional Qwen3.8-27B GGUF, are
  downloaded separately from their upstream model repositories after setup is invoked and retain
  their upstream model licenses; neither artifact is part of this repository.
- `jackwener/llm-wiki` is architectural reference material, not a runtime dependency; its code is
  not vendored here.

The Apache-2.0 header retained in `apps/api/knowledge_agent/__init__.py` originates from the Google
ADK scaffold and remains under that file's stated terms.

## User data

Knemora does not relicense uploaded documents, datasets, generated organizational knowledge, or
other user data. Users retain their rights and remain responsible for the material they process.
