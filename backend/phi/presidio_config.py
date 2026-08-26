"""Presidio analyzer/anonymizer setup, including custom AADHAAR/PAN recognizers.

The analyzer is built lazily on first use (rather than at import time) so that
importing this module never forces a spaCy model load — only code paths that
actually need redaction pay that cost.
"""

from __future__ import annotations

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

NLP_ENGINE_NAME = "spacy"
SPACY_MODEL = "en_core_web_lg"

# Default Presidio entities plus the two custom recognizers below.
DEFAULT_ENTITIES = [
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "DATE_TIME",
    "LOCATION",
    "MEDICAL_LICENSE",
    "US_SSN",
]

CUSTOM_ENTITIES = ["AADHAAR", "PAN"]

ALL_ENTITIES = DEFAULT_ENTITIES + CUSTOM_ENTITIES


def _build_aadhaar_recognizer() -> PatternRecognizer:
    """12-digit Aadhaar number, optionally space/hyphen grouped as 4-4-4."""
    pattern = Pattern(
        name="aadhaar_pattern",
        regex=r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        score=0.6,
    )
    return PatternRecognizer(
        supported_entity="AADHAAR",
        patterns=[pattern],
        context=["aadhaar", "uidai", "unique identification"],
    )


def _build_pan_recognizer() -> PatternRecognizer:
    """Indian PAN: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)."""
    pattern = Pattern(
        name="pan_pattern",
        regex=r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        score=0.7,
    )
    return PatternRecognizer(
        supported_entity="PAN",
        patterns=[pattern],
        context=["pan", "permanent account number", "income tax"],
    )


@lru_cache(maxsize=1)
def get_analyzer() -> AnalyzerEngine:
    """Build (once) and return the Presidio AnalyzerEngine with custom recognizers."""
    nlp_configuration = {
        "nlp_engine_name": NLP_ENGINE_NAME,
        "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    analyzer.registry.add_recognizer(_build_aadhaar_recognizer())
    analyzer.registry.add_recognizer(_build_pan_recognizer())
    return analyzer


@lru_cache(maxsize=1)
def get_anonymizer() -> AnonymizerEngine:
    """Build (once) and return the Presidio AnonymizerEngine."""
    return AnonymizerEngine()
