# Native converter fixture

`whiteboard-cli-0.2.13.json` is an actual local OpenAPI export made by the installed whiteboard-cli 0.2.13 on 2026-10-08. Input is the built-in layout of `def flow(x): if x: return True; return False` in app.py. It exercises zero-radius rectangle export, rich-text bold inheritance, caption styles and omitted container parents. It contains no online publication or host execution record.

Container and relative-coordinate normalization follows the official board-v1 data-structure specification checked during implementation. Tests use synthetic export receipts only to exercise rejection rules; they are not online acceptance evidence.
