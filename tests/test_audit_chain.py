"""Audit trail tamper evidence: SHA-256 hash chaining (IEC 62304 / ISO 13485).

Each event carries the hash of the event before it, so editing or deleting one
event invalidates every event after it. This is tamper EVIDENCE, not tamper
proof - anyone who can write the file can recompute the chain - and it is aimed
at the failure that actually happens to an audit trail: a hand edit, a partial
restore, or a writer that truncates. The repository has already been bitten by
the last one; see _read_event_log's docstring, where one unparseable byte plus
one POST took a 23-event trail down to 1 and answered 200 "recorded".

The 547 events written before 2026-09-18 carry no chain fields. They are
reported as an unverifiable prefix, not as a break, because a check that calls
every pre-existing record "tampered" is a check everyone learns to ignore.
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _chain(events):
    """Link a list of bare events the way append_event_log does."""
    out = []
    prev = main.AUDIT_GENESIS_HASH
    for ev in events:
        ev = dict(ev)
        ev["prev_hash"] = prev
        ev["hash"] = main.audit_event_hash(ev, prev)
        prev = ev["hash"]
        out.append(ev)
    return out


def _events(n):
    return [{"event_id": f"EVT-{i:04d}", "sequence": i + 1, "event_type": "alarm",
             "severity_level": 3, "cpri_percent": 90.0 + i} for i in range(n)]


def test_empty_and_legacy_trails_are_not_failures():
    assert main.verify_audit_chain([])["status"] == "empty"
    legacy = main.verify_audit_chain(_events(3))
    assert legacy["status"] == "legacy_only"
    assert legacy["legacy_events"] == 3
    assert legacy["broken_at"] is None


def test_a_chained_trail_verifies():
    rep = main.verify_audit_chain(_chain(_events(5)))
    assert rep["status"] == "intact"
    assert rep["chained_events"] == 5
    assert rep["legacy_events"] == 0


def test_legacy_prefix_then_chained_events_verifies():
    logs = _events(2) + _chain(_events(3))
    rep = main.verify_audit_chain(logs)
    assert rep["status"] == "intact"
    assert rep["legacy_events"] == 2
    assert rep["chained_events"] == 3


def test_editing_an_events_content_breaks_the_chain():
    logs = _chain(_events(5))
    logs[2]["cpri_percent"] = 12.3          # the edit an attacker would make
    rep = main.verify_audit_chain(logs)
    assert rep["status"] == "broken"
    assert rep["broken_at"]["index"] == 2
    assert "does not match its hash" in rep["broken_at"]["reason"]


def test_deleting_an_event_breaks_the_chain():
    logs = _chain(_events(5))
    del logs[2]
    rep = main.verify_audit_chain(logs)
    assert rep["status"] == "broken"
    # index 2 is now the old event 3, whose prev_hash points at the deleted one
    assert rep["broken_at"]["index"] == 2
    assert "prev_hash" in rep["broken_at"]["reason"]


def test_reordering_events_breaks_the_chain():
    logs = _chain(_events(5))
    logs[1], logs[3] = logs[3], logs[1]
    assert main.verify_audit_chain(logs)["status"] == "broken"


def test_stripping_chain_fields_after_the_chain_began_is_a_break():
    """Silently dropping the fields must not downgrade to 'legacy'."""
    logs = _chain(_events(4))
    logs[2].pop("hash")
    rep = main.verify_audit_chain(logs)
    assert rep["status"] == "broken"
    assert rep["broken_at"]["reason"] == "chain fields missing"


def test_the_hash_ignores_key_order_but_not_values():
    ev = {"event_id": "EVT-1", "severity_level": 3, "cpri_percent": 90.0}
    reordered = {"cpri_percent": 90.0, "event_id": "EVT-1", "severity_level": 3}
    g = main.AUDIT_GENESIS_HASH
    assert main.audit_event_hash(ev, g) == main.audit_event_hash(reordered, g)
    assert main.audit_event_hash(ev, g) != main.audit_event_hash(
        {**ev, "cpri_percent": 90.1}, g)
    # and the link itself is part of the digest
    assert main.audit_event_hash(ev, g) != main.audit_event_hash(ev, "f" * 64)


def test_the_write_path_still_chains_and_records_the_action_type():
    """A guard on the wiring, not just the algorithm.

    The helpers above can be perfect while append_event_log forgets to call
    them. Anchored on behaviour-bearing names rather than a literal line so a
    reformat does not fail it.
    """
    src = inspect.getsource(main.create_app)
    for needed in ('event["prev_hash"] = prev_hash',
                   'event["hash"] = audit_event_hash(event, prev_hash)',
                   '"event_type": event_type',
                   'verify_audit_chain(logs)'):
        assert needed in src, f"append_event_log no longer does: {needed}"


def test_the_real_trail_on_disk_verifies():
    """The shipped Data/extubation_events_audit.json must not report broken."""
    path = os.path.join(main.DATA_ROOT, "extubation_events_audit.json")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        logs = json.load(fh)
    rep = main.verify_audit_chain(logs)
    assert rep["status"] in ("empty", "legacy_only", "intact"), rep
