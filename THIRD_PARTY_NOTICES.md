# Third-party notices

## Runtime dependency

- Project: [jacob-bd/perplexity-web-mcp](https://github.com/jacob-bd/perplexity-web-mcp)
- Python package: `perplexity-web-mcp-cli` 0.16.1
- Pinned revision: `e34b5082d6c16283358d8a1e3cbd7fa61c35fc0d`
- License: [MIT at the pinned revision](https://github.com/jacob-bd/perplexity-web-mcp/blob/e34b5082d6c16283358d8a1e3cbd7fa61c35fc0d/LICENSE)
- Original copyright notice: Copyright (c) 2025 Henrique
- Upstream credits [henrique-coder/perplexity-webui-scraper](https://github.com/henrique-coder/perplexity-webui-scraper).

The upstream source tree is not vendored here. Installation fetches the pinned dependency. The original copyright and MIT permission text are retained in this repository's LICENSE alongside the local modifications attribution. Other Python dependencies retain their respective licenses in their distributions.

## Protocol and integration references

- [Native file upload / MCP integration discussion](https://github.com/jacob-bd/perplexity-web-mcp/issues/56)
- [cloudomate/claude-proxy](https://github.com/cloudomate/claude-proxy): reference for translating tool_use/tool_result and SSE input_json_delta. Its source code is not included here.
- [nearyou/perplexity-ai](https://github.com/nearyou/perplexity-ai): file upload behavior reference; source code is not included here.
- [farion1231/cc-switch](https://github.com/farion1231/cc-switch): optional external client configuration tool; not redistributed here.

The local Python adapter, file helper, launcher adaptations, setup scripts and tests are published in this repository. The MIT grant covers code, not access to third-party accounts or services.
