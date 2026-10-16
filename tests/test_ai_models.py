"""Model discovery, the key check, and fallback between models (ai.py).

Free-tier keys cannot call every Gemini model, and a single hard-coded model
locked new users out. These pin how ai.py decides what a key can use and what
it does when a model refuses a request.

The Gemini SDK is faked at the three module attributes ai.py touches -
genai.configure, genai.list_models and genai.GenerativeModel - with errors
taken from google.api_core, the same classes the real SDK raises.
"""
from types import SimpleNamespace

import pytest
from google.api_core import exceptions as google_errors

import ai

NO_FREE_TIER = google_errors.ResourceExhausted(
    "You exceeded your current quota. Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.5-pro"
)
SPENT = google_errors.ResourceExhausted(
    "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-2.5-flash"
)
GONE = google_errors.NotFound("models/gemini-1.5-flash is not found")
OVERLOADED = google_errors.ServiceUnavailable("The model is overloaded. Please try again later.")


def fake_gemini(monkeypatch, listed=(), errors=None, list_error=None):
    """`listed`: model ids list_models() returns. `errors`: model -> exception
    its generate_content raises (others succeed). Returns the list of models
    generate_content was called on, in order."""
    errors = errors or {}
    calls = []

    def list_models(**kwargs):
        if list_error:
            raise list_error
        for name in listed:
            yield SimpleNamespace(name=f"models/{name}", supported_generation_methods=["generateContent"])
        yield SimpleNamespace(name="models/text-embedding-004", supported_generation_methods=["embedContent"])

    class Model:
        def __init__(self, name):
            self.name = name

        def generate_content(self, *args, **kwargs):
            calls.append(self.name)
            if self.name in errors:
                raise errors[self.name]
            return SimpleNamespace(text='{"ok": true}')

    monkeypatch.setattr(ai.genai, "configure", lambda **kwargs: None)
    monkeypatch.setattr(ai.genai, "list_models", list_models)
    monkeypatch.setattr(ai.genai, "GenerativeModel", Model)
    return calls


# --- check_models ------------------------------------------------------------

def test_check_sorts_each_model_into_a_status(monkeypatch):
    fake_gemini(
        monkeypatch,
        listed=["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        errors={"gemini-2.5-pro": NO_FREE_TIER, "gemini-2.5-flash": SPENT, "gemini-2.0-flash": GONE},
    )
    key_ok, message, results = ai.check_models("key")
    assert key_ok
    assert {r["model"]: r["status"] for r in results} == {
        "gemini-2.5-flash": ai.BUSY,
        "gemini-2.0-flash": ai.UNAVAILABLE,
        "gemini-2.5-flash-lite": ai.OK,
        "gemini-2.5-pro": ai.NOT_FREE,
    }
    assert message == "2 of 4 models work with this key."
    # A model that worked just now beats one that is allowed but spent.
    assert ai.recommended_model(results) == "gemini-2.5-flash-lite"
    assert ai.usable_models(results) == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_check_only_probes_plain_gemini_family_ids(monkeypatch):
    calls = fake_gemini(monkeypatch, listed=[
        "gemini-2.5-flash", "gemini-3-pro-preview",
        "gemini-2.5-flash-preview-09-2025", "gemini-2.0-flash-001", "gemini-flash-latest",
        "gemini-2.5-flash-image", "gemini-2.5-flash-preview-tts", "gemma-3-27b-it",
    ])
    _, _, results = ai.check_models("key")
    assert [r["model"] for r in results] == ["gemini-2.5-flash", "gemini-3-pro-preview"]
    assert sorted(calls) == ["gemini-2.5-flash", "gemini-3-pro-preview"]


def test_check_reports_a_rejected_key_without_probing(monkeypatch):
    calls = fake_gemini(monkeypatch, list_error=google_errors.InvalidArgument("API key not valid."))
    key_ok, message, results = ai.check_models("bad")
    assert not key_ok
    assert message == "The key was rejected: API key not valid."
    assert results == [] and calls == []


def test_check_with_nothing_usable(monkeypatch):
    fake_gemini(monkeypatch, listed=["gemini-2.5-pro"], errors={"gemini-2.5-pro": NO_FREE_TIER})
    key_ok, message, results = ai.check_models("key")
    assert key_ok
    assert message == "None of the 1 models work with this key right now."
    assert ai.recommended_model(results) is None


def test_check_falls_back_to_the_default_when_no_names_match(monkeypatch):
    calls = fake_gemini(monkeypatch, listed=["gemini-ultra-next"])
    _, _, results = ai.check_models("key")
    assert [r["model"] for r in results] == [ai.GEMINI_MODEL]
    assert calls == [ai.GEMINI_MODEL]


def test_empty_key_is_not_sent(monkeypatch):
    calls = fake_gemini(monkeypatch, listed=["gemini-2.5-flash"])
    assert ai.check_models("  ") == (False, "Paste a key first.", [])
    assert calls == []


def test_rank_prefers_stable_flash_and_newer_versions():
    names = ["gemini-2.5-pro", "gemini-3-flash-preview", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-3-flash"]
    assert sorted(names, key=ai.model_rank) == [
        "gemini-3-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3-flash-preview",
    ]


# --- fallback ----------------------------------------------------------------

@pytest.mark.parametrize("error", [SPENT, NO_FREE_TIER, GONE, OVERLOADED])
def test_call_moves_to_the_next_model_when_one_cannot_serve(monkeypatch, error):
    calls = fake_gemini(monkeypatch, errors={"gemini-2.5-flash": error})
    fallbacks = []
    result = ai.screen_job_description(
        "JD", "key", models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        on_fallback=lambda used, skipped: fallbacks.append((used, [m for m, _ in skipped])),
    )
    assert result["keywords"] == []
    assert calls == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert fallbacks == [("gemini-2.5-flash-lite", ["gemini-2.5-flash"])]


def test_no_fallback_notice_when_the_first_choice_answers(monkeypatch):
    calls = fake_gemini(monkeypatch)
    fallbacks = []
    ai.rewrite_resume("JD", {}, "", "key", models=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
                      on_fallback=lambda *a: fallbacks.append(a))
    assert calls == ["gemini-2.5-flash"]
    assert fallbacks == []


def test_other_errors_are_not_retried_on_another_model(monkeypatch):
    calls = fake_gemini(monkeypatch, errors={"gemini-2.5-flash": google_errors.InvalidArgument("bad request")})
    with pytest.raises(google_errors.InvalidArgument):
        ai.parse_resume_pdf(b"%PDF", "key", models=["gemini-2.5-flash", "gemini-2.5-flash-lite"])
    assert calls == ["gemini-2.5-flash"]


def test_every_model_failing_names_each_one(monkeypatch):
    fake_gemini(monkeypatch, errors={"gemini-2.5-flash": SPENT, "gemini-2.5-pro": NO_FREE_TIER})
    with pytest.raises(ai.ModelsUnavailable) as raised:
        ai.screen_job_description("JD", "key", models=["gemini-2.5-flash", "gemini-2.5-pro"])
    message = str(raised.value)
    assert "gemini-2.5-flash (quota used up for now)" in message
    assert "gemini-2.5-pro (not on the free tier)" in message


def test_no_models_given_uses_the_default(monkeypatch):
    calls = fake_gemini(monkeypatch)
    ai.screen_job_description("JD", "key")
    assert calls == [ai.GEMINI_MODEL]


def test_chat_reports_exhausted_models_as_a_failed_answer(monkeypatch):
    fake_gemini(monkeypatch, errors={"gemini-2.5-flash": SPENT})
    ok, reply = ai.answer_application_question([], "", {}, None, "key", models=["gemini-2.5-flash"])
    assert not ok
    assert "quota used up for now" in reply
