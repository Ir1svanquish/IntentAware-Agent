"""Language selected once at startup and shared with background workers."""

from intentaware.translations_en import ENGLISH

DEFAULT_LANGUAGE = "zh"
LANGUAGE_SETTING = "language"
LANGUAGES = ("zh", "en")
_language = DEFAULT_LANGUAGE


def set_language(language: str) -> None:
    global _language
    _language = "en" if language == "en" else DEFAULT_LANGUAGE


def get_language() -> str:
    return _language


def english(message: str) -> str:
    return ENGLISH.get(message, message)


def tr(message: str, *values: object) -> str:
    text = english(message) if _language == "en" else message
    return text.format(*values) if values else text


def feedback_prompt(system: str) -> str:
    if _language == "en":
        return system + (
            "\n\nWrite all user-facing feedback in English. Keep JSON field names and enum values "
            "unchanged. Interpret character limits as limits on English characters. "
            "Preserve exact quotations, names, and source excerpts in their original language."
        )
    return system
