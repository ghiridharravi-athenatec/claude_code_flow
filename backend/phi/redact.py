"""The single PHI-redaction helper used by every logging and error-response path.

Per CLAUDE.md, no module outside ``phi/`` may implement PHI detection logic —
every caller that might be handling record text imports ``redact_for_logging``
from here instead.
"""

from __future__ import annotations

import logging

from presidio_anonymizer.entities import OperatorConfig

from phi.presidio_config import ALL_ENTITIES, get_analyzer, get_anonymizer

logger = logging.getLogger(__name__)

_ANONYMIZER_OPERATORS = {
    entity: OperatorConfig("replace", {"new_value": f"<{entity}>"}) for entity in ALL_ENTITIES
}


def redact_for_logging(text: str | None) -> str:
    """Return ``text`` with every detected PHI entity replaced by an ``<ENTITY>`` tag.

    Safe to call on any string that might contain extracted record content —
    this is the only sanctioned path for record text to reach a log line or an
    error response body (CLAUDE.md PHI rules #2 and #3).
    """
    if not text:
        return ""

    try:
        analyzer = get_analyzer()
        anonymizer = get_anonymizer()
        results = analyzer.analyze(text=text, entities=ALL_ENTITIES, language="en")
        anonymized = anonymizer.anonymize(
            text=text, analyzer_results=results, operators=_ANONYMIZER_OPERATORS
        )
        return anonymized.text
    except Exception:
        # If redaction itself fails, never fall back to returning raw text.
        logger.error("PHI redaction failed; withholding original text from output.")
        return "<REDACTION_FAILED>"
