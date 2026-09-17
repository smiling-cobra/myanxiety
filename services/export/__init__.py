"""The therapist-shareable export, v0.

The product bet this exists to test is narrow: will someone actually take their
journal into a therapy session? So this is deliberately rough — plain Markdown,
one file, the last few weeks — and it ships before it is designed, because a
polished artifact that nobody brings to a session answers nothing. Phase 6
reworks the format once there is evidence it is used.

Two properties are deliberate rather than rough:

* **No model call.** The file is built from what is stored, deterministically.
  It costs nothing against the LLM budget, it cannot fail because Anthropic is
  down, and nothing in it was written by anyone but the user — which matters
  for a document handed to a clinician.
* **It is the user's own words in full.** The file goes to them, in their own
  chat, and where it goes next is their choice. Nothing is summarised away and
  nothing the user did not write is added beyond counts and dates.

Tags are read through `services.tags`, so the themes line reflects the current
vocabulary however old the entries are.

`ExportService`, `Export` and `EXPORT_DAYS` are the public surface. `service.py`
loads what is stored and packages the file; `markdown.py` lays it out.
"""
from services.export.service import EXPORT_DAYS, Export, ExportService

__all__ = ['EXPORT_DAYS', 'Export', 'ExportService']
