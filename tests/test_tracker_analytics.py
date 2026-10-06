"""Unit coverage for the pure helpers at the top of firebase_dashboard.py:
funnel counting, browser-timezone formatting and the login lockout rules.
None of these need Streamlit or Firestore."""
from datetime import datetime, timedelta, timezone

import firebase_dashboard as fd


# --- funnel -----------------------------------------------------------------
def test_funnel_counts_rejected_after_interview_as_interviewed():
    records = [
        {"status": "Applied", "interview_date": None},
        {"status": "Interviewing", "interview_date": datetime(2026, 10, 1)},
        {"status": "Rejected", "interview_date": datetime(2026, 9, 20)},   # interviewed, then rejected
        {"status": "Rejected", "interview_date": None},                    # rejected at screening
        {"status": "Offered", "interview_date": None},                     # offer implies an interview
    ]
    assert fd.funnel_counts(records) == (5, 3, 1)


def test_funnel_counts_empty():
    assert fd.funnel_counts([]) == (0, 0, 0)


# --- timezone ----------------------------------------------------------------
def test_browser_timezone_prefers_iana_name():
    tz = fd.browser_timezone("Asia/Taipei", -480)
    assert fd.format_local_time(datetime(2026, 10, 6, 7, 52, tzinfo=timezone.utc), tz) == "2026-10-06 15:52"


def test_browser_timezone_falls_back_to_js_offset():
    # JS getTimezoneOffset() for UTC+8 is -480.
    tz = fd.browser_timezone(None, -480)
    assert fd.format_local_time(datetime(2026, 10, 6, 7, 52), tz) == "2026-10-06 15:52"


def test_browser_timezone_falls_back_to_utc_when_context_is_missing():
    tz = fd.browser_timezone(None, None)
    assert fd.format_local_time(datetime(2026, 10, 6, 7, 52), tz) == "2026-10-06 07:52"
    assert fd.format_local_time(None, tz) == "N/A"


def test_browser_timezone_ignores_bogus_name():
    tz = fd.browser_timezone("Not/AZone", 0)
    assert fd.format_local_time(datetime(2026, 10, 6, 7, 52), tz) == "2026-10-06 07:52"


# --- login lockout ------------------------------------------------------------
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def test_failures_count_up_then_lock_on_the_fifth():
    data = {}
    for expected in range(1, fd.MAX_LOGIN_ATTEMPTS):
        update = fd.login_failure_update(data, NOW)
        assert update == {"failed_attempts": expected, "locked_until": None}
        data = update
    final = fd.login_failure_update(data, NOW)
    assert final["failed_attempts"] == 0
    assert final["locked_until"] == NOW + timedelta(minutes=fd.LOCKOUT_MINUTES)


def test_lockout_remaining_rounds_up_and_expires():
    locked = {"locked_until": NOW + timedelta(minutes=4, seconds=30)}
    assert fd.login_lockout_remaining(locked, NOW) == 5
    assert fd.login_lockout_remaining(locked, NOW + timedelta(minutes=10)) == 0
    assert fd.login_lockout_remaining({}, NOW) == 0
    assert fd.login_lockout_remaining({"locked_until": None}, NOW) == 0


class _Doc:
    def __init__(self, data):
        self._data = data
        self.exists = True

    def to_dict(self):
        return dict(self._data)


class _DocRef:
    def __init__(self, data):
        self.data = data
        self.updates = []

    def get(self):
        return _Doc(self.data)

    def update(self, fields):
        self.updates.append(fields)
        self.data.update(fields)


class _Db:
    def __init__(self, ref):
        self.ref = ref

    def collection(self, *a):
        return self

    def document(self, *a):
        return self.ref


def test_authenticate_user_locks_after_repeated_wrong_passwords():
    from werkzeug.security import generate_password_hash

    ref = _DocRef({"password_hash": generate_password_hash("right")})
    db = _Db(ref)
    for _ in range(fd.MAX_LOGIN_ATTEMPTS - 1):
        ok, msg = fd.authenticate_user(db, "a@b.c", "wrong")
        assert (ok, msg) == (False, fd.LOGIN_FAILED_MESSAGE)
    ok, msg = fd.authenticate_user(db, "a@b.c", "wrong")
    assert not ok and "Too many failed attempts" in msg
    # Locked: even the right password is refused until the lockout passes.
    ok, msg = fd.authenticate_user(db, "a@b.c", "right")
    assert not ok and "Too many failed attempts" in msg


def test_authenticate_user_success_resets_counter():
    from werkzeug.security import generate_password_hash

    ref = _DocRef({"password_hash": generate_password_hash("right"), "failed_attempts": 3})
    ok, msg = fd.authenticate_user(_Db(ref), "a@b.c", "right")
    assert ok
    assert ref.updates == [{"failed_attempts": 0, "locked_until": None}]


# --- enumeration-safe messages -------------------------------------------------
class _MissingDoc:
    exists = False

    def to_dict(self):
        return {}


class _MissingRef:
    def get(self):
        return _MissingDoc()


def test_unknown_email_and_wrong_password_get_the_same_message():
    from werkzeug.security import generate_password_hash

    unknown = fd.authenticate_user(_Db(_MissingRef()), "nobody@b.c", "x")
    wrong = fd.authenticate_user(_Db(_DocRef({"password_hash": generate_password_hash("right")})), "a@b.c", "wrong")
    assert unknown == wrong == (False, fd.LOGIN_FAILED_MESSAGE)


# --- registration throttle -------------------------------------------------------
def test_validate_credentials():
    assert fd.validate_credentials("", "password1") == "Email and password are required."
    assert fd.validate_credentials("not-an-email", "password1") == "Enter a valid email address."
    assert fd.validate_credentials("a@b.c", "short") == f"Password must be at least {fd.MIN_PASSWORD_LENGTH} characters."
    assert fd.validate_credentials("a@b.c", "longenough") is None


def test_registration_allowed_caps():
    assert fd.registration_allowed(0, 0) == (True, None)
    assert fd.registration_allowed(fd.MAX_REGISTRATIONS_PER_DAY, 0)[0] is False
    assert fd.registration_allowed(0, fd.MAX_REGISTRATIONS_PER_IP_PER_DAY)[0] is False
    assert fd.registration_allowed(fd.MAX_REGISTRATIONS_PER_DAY - 1, fd.MAX_REGISTRATIONS_PER_IP_PER_DAY - 1) == (True, None)


def test_ip_bucket_is_hashed_and_stable():
    a, b = fd.ip_bucket("203.0.113.9"), fd.ip_bucket("203.0.113.9")
    assert a == b and len(a) == 16 and "203" not in a
    assert fd.ip_bucket(None) == fd.ip_bucket(None) != a


class _Store:
    """Fake Firestore keyed by collection name; records set() calls."""

    def __init__(self, docs):
        self.docs = docs          # {(collection, doc_id): dict}
        self.sets = []

    def collection(self, name):
        store = self

        class _Coll:
            def document(self, doc_id):
                key = (name, doc_id)

                class _Ref:
                    def get(self_inner):
                        data = store.docs.get(key)
                        doc = _Doc(data) if data is not None else _MissingDoc()
                        return doc

                    def set(self_inner, fields, merge=False):
                        store.sets.append((key, fields, merge))
                        store.docs.setdefault(key, {}).update({k: v for k, v in fields.items()})

                return _Ref()

        return _Coll()


def test_register_user_creates_account_and_counts_it():
    store = _Store({})
    ok, msg = fd.register_user(store, "new@b.c", "longenough", client_ip="203.0.113.9")
    assert ok, msg
    collections = [key[0] for key, _, _ in store.sets]
    assert "user_auth" in collections
    assert fd.REGISTRATION_LIMITS_COLLECTION in collections
    assert "password_hash" in store.docs[("user_auth", "new@b.c")]


def test_register_user_refuses_when_todays_cap_is_reached():
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store = _Store({(fd.REGISTRATION_LIMITS_COLLECTION, today): {"total": fd.MAX_REGISTRATIONS_PER_DAY}})
    ok, msg = fd.register_user(store, "new@b.c", "longenough")
    assert not ok and "paused" in msg
    assert store.sets == []


def test_register_user_refuses_per_ip_cap_without_revealing_accounts():
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bucket = fd.ip_bucket("203.0.113.9")
    store = _Store({(fd.REGISTRATION_LIMITS_COLLECTION, today): {"total": 1, "ips": {bucket: fd.MAX_REGISTRATIONS_PER_IP_PER_DAY}}})
    ok, msg = fd.register_user(store, "new@b.c", "longenough", client_ip="203.0.113.9")
    assert not ok and "network" in msg


def test_register_user_existing_email_does_not_say_registered():
    store = _Store({("user_auth", "a@b.c"): {"password_hash": "x"}})
    ok, msg = fd.register_user(store, "a@b.c", "longenough")
    assert not ok
    assert "already registered" not in msg.lower()
    assert all(key[0] != "user_auth" for key, _, _ in store.sets)
