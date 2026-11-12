# API tools delivery

Did all 26 tool switches and all 39 required provider/tool live cases. Each final case exited 0. The frozen prefix and four-field reply stay intact. New tools default off; web search/fetch and Claude history caching default on.

Proof date: 2026-11-11. Models: OpenAI `gpt-6.1-sol`; Anthropic `claude-opus-5-5`.

## Per-tool results

Each row names one provider/tool pair. “Works” means the specific live case passed through the real launcher, schema, display gate and SQLite. The exact scope of screen, browser and file checks is below. Provider features not offered on a lane are omitted, rather than counted as a passed test.

| Provider | Switch | Result | Default | Live exit codes | Default reason |
| --- | --- | --- | --- | --- | --- |
| openai | `--web-search` | works | on | 0 | Keeps the existing lookup behavior. |
| anthropic | `--web-search` | works | on | 0 | Keeps the existing lookup behavior. |
| openai | `--web-fetch` | works | on | 0 | Keeps the existing lookup behavior. |
| anthropic | `--web-fetch` | works | on | 0 | Keeps the existing lookup behavior. |
| anthropic | `--history-cache` | works | on | 0, 0, 0 | Cuts repeated input without changing the answer. |
| anthropic | `--memory` | works | off | 0, 0 | Adds lasting notes across chats. |
| openai | `--code-execution` | works | off | 0 | Uses a paid hosted runtime. |
| anthropic | `--code-execution` | works | off | 0 | Uses a paid hosted runtime. |
| openai | `--computer` | works | off | 0 | Can change the device. |
| anthropic | `--computer` | works | off | 0 | Can change the device. |
| anthropic | `--browser` | works | off | 0 | Can act on signed-in websites. |
| openai | `--shell` | works | off | 0 | Can change files and devices. |
| anthropic | `--shell` | works | off | 0 | Can change files and devices. |
| openai | `--hosted-shell` | works | off | 0 | Uses a paid hosted runtime. |
| anthropic | `--text-editor` | works | off | 0 | Can change files. |
| openai | `--apply-patch` | works | off | 0 | Can change files. |
| openai | `--mcp-local` | works | off | 0 | Exposes device actions to the model. |
| anthropic | `--mcp-local` | works | off | 0 | Exposes device actions to the model. |
| openai | `--mcp-remote` | works | off | 0 | Sends tool requests through a remote endpoint. |
| anthropic | `--mcp-remote` | works | off | 0 | Sends tool requests through a remote endpoint. |
| openai | `--files` | works | off | 0 | Stores files with the API provider. |
| anthropic | `--files` | works | off | 0 | Stores files with the API provider. |
| openai | `--file-search` | works | off | 0 | Uses provider storage and retrieval. |
| openai | `--skills` | works | off | 0 | Runs skill instructions and supporting code. |
| anthropic | `--skills` | works | off | 0 | Runs skill instructions and supporting code. |
| openai | `--tool-search` | works | off | 0 | Changes how tools enter model context. |
| anthropic | `--tool-search` | works | off | 0 | Changes how tools enter model context. |
| openai | `--programmatic` | works | off | 0 | Changes tool execution and adds runtime cost. |
| anthropic | `--programmatic` | works | off | 0 | Changes tool execution and adds runtime cost. |
| anthropic | `--context-editing` | works | off | 0 | Removes old detail from the model input. |
| openai | `--compaction` | works | off | 0, 0 | Changes the context sent to the model. |
| anthropic | `--compaction` | works | off | 0, 0 | Changes the context sent to the model. |
| openai | `--background` | works | off | 0 | Changes storage and request lifetime. |
| openai | `--image-generation` | works | off | 0 | Adds image-generation charges. |
| anthropic | `--api-advisor` | works | off | 0 | Calls another paid model. |
| openai | `--functions` | works | off | 0 | Exposes local command execution. |
| anthropic | `--functions` | works | off | 0 | Exposes local command execution. |
| openai | `--custom-tools` | works | off | 0 | Exposes local command execution. |
| openai | `--namespaces` | works | off | 0 | Changes tool names and discovery. |

## Deciding evidence

- Claude memory was written in one named session and recalled in a different new session, using a random marker.
- Each skill was uploaded with a secret random marker; the live reply recovered that marker from its skill file.
- File search recovered a marker from the uploaded proof document. Both Files API cases recovered the exact sentence from an attached PDF.
- Both local MCP cases and both remote MCP cases returned real phone notification data, limited to five items. Discovery and permission records are distinct from actual MCP calls.
- Computer proof captured Android Settings on the hidden `astra-api-proof` display. Browser proof listed existing tabs. No visible-phone taps or Yana actions were part of the proof.
- Image generation produced an actual image file. The final merged-code check also included its saved local path in the displayed answer.
- The tool-list stability tests compare complete serialized tool definitions for unchanged configuration.
- A final answer cannot claim a named tool was used without a matching receipt. An unfinished web call is rejected. The latest failed action cannot use an earlier success to claim completion.

### Claude conversation cache

| Turn | Total input tokens | Cache-read tokens |
| --- | ---: | ---: |
| 1 | 15842 | 0 |
| 2 | 20828 | 15838 |
| 3 | 21034 | 20824 |

The changing loop note used to replace the front of the conversation, breaking the cache prefix. The note now stays with its own exchange. The third request reads earlier conversation tokens, beyond the entire first request's input. One automatic history marker plus the two system-page markers stays within the provider's four-marker limit.

## Fixes proved during the work

- OpenAI image generation rejected its implicit maximum complexity for this model. The tool definition now uses the supported `high` setting, proved live.
- Claude browser tab operations require only `browser_state` in successful results. Extra text caused HTTP 400; the corrected shape passed.
- Claude programmatic tool calling rejects `disable_parallel_tool_use: true`. Programmatic mode now sends the supported `auto` choice without that setting.
- The temporary tunnel adapter originally missed chunked request bodies. It now handles them. Quick tunnels then timed out. The installed route uses a separate authenticated Cloudflare relay; the existing ngrok endpoint was left in place.
- The relay has separate client and phone-bridge tokens. It queues requests in memory only. The phone opens an outbound bridge for the duration of a remote-MCP call.
- The merged test for advisor-note placement now checks that old history stays first and the new loop note comes later. Operator `/advisor` and Anthropic `--api-advisor` remain separate switches.

## Exact check limits

- Computer proof captures the hidden Settings screen; touch-adapter right-click, middle-click and cursor-position are withheld. Other computer actions were not all exercised live.
- Browser proof lists tabs; no signed-in forms were submitted.
- Files API upload/reference passed live on both providers. Output download and local path announcement have fixture tests; image path announcement passed live.
- The remote relay live proof exposes only android_notification_list, limit 5. Other remote tools require deliberate allowlist configuration.
- Provider-native tunnel IDs were not used; an authenticated public MCP URL was proved.

No tool type in the requested provider/model pairs remains marked unavailable after the successful proofs. Three mouse-only members are withheld by the phone adapter; this is a local hardware limit, not a provider/account denial.

## Verification totals

320 merged offline tests passed. Four native terminal tests passed. All 39 required live cases passed with exit code 0, including every step of the multi-call cases. The final merged-code reruns covered both remote MCP lanes, image saving, and the three-turn Claude cache.

## Receipts and reproduction

Full private JSON summary: `state/api-tools/verification-summary.json` in the API-tools development copy. It names every individual report and its SHA-256 hash. Reports include live exit codes, database rows, tool receipts and command results. Full records remain local because they include phone notifications and screen paths.

Run `verify_tools.py --engine ENGINE --case TOOL --state PRIVATE_DIRECTORY` for a bounded live check. For remote MCP, pass its private `--options-file`. Paid calls use the existing key files without printing them. Run the verification commands in README for offline and native tests.

## Official references

- [OpenAI tools](https://developers.openai.com/api/docs/guides/tools)
- [OpenAI remote MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction)
- [Anthropic tool reference](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-reference)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic browser tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-tool)
- [Cloudflare Worker deployment API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/update/)
