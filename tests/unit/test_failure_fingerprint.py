from __future__ import annotations

from littlehive.core.runtime.errors import classify_error
from littlehive.core.runtime.recovery import upsert_failure_fingerprint
from littlehive.db.models import FailureFingerprint
from littlehive.db.session import Base, create_session_factory


def test_failure_fingerprint_normalization_and_dedupe(tmp_path):
    session_factory, engine = create_session_factory(f"sqlite:///{tmp_path / 'ff.db'}")
    import littlehive.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    info1 = classify_error(RuntimeError("Timeout code 500 on provider 123"), category="provider", component="router")
    info2 = classify_error(RuntimeError("Timeout code 500 on provider 999"), category="provider", component="router")

    with session_factory() as db:
        upsert_failure_fingerprint(db, info1)
        upsert_failure_fingerprint(db, info2)
        db.commit()

        rows = db.query(FailureFingerprint).all()
        assert len(rows) == 1
        assert rows[0].occurrence_count == 2
