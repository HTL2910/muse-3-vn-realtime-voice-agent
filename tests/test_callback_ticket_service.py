import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.callback.callback_ticket_service import (
    CallbackTicketService, TicketStatus, SLA_HOURS)

NOW = 1_700_000_000.0

def svc(**kw):
    return CallbackTicketService(dedup_window_s=3600, **kw)

def test_create_writes_ticket_and_outbox_atomically():
    s = svc()
    t = s.create_ticket(phone="0901234567", intent="order_status", summary="Tra don DH1",
                        call_id="c1", idempotency_key="k1", now=NOW)
    assert t.ticket_code.startswith("CB") and not t.deduplicated
    assert s.count_tickets() == 1 and s.count_outbox("pending") == 1
    assert t.status == TicketStatus.QUEUED

def test_same_idempotency_key_no_duplicate():
    s = svc()
    a = s.create_ticket(phone="0901", intent="order_status", call_id="c1", idempotency_key="same", now=NOW)
    b = s.create_ticket(phone="0901", intent="order_status", call_id="c2", idempotency_key="same", now=NOW + 10)
    assert a.ticket_id == b.ticket_id and b.deduplicated
    assert s.count_tickets() == 1 and s.count_outbox() == 1

def test_dedup_phone_intent_within_window_but_not_after():
    s = svc()
    a = s.create_ticket(phone="0902", intent="refund", call_id="c1", now=NOW)
    b = s.create_ticket(phone="0902", intent="refund", call_id="c2", now=NOW + 600)
    assert b.ticket_id == a.ticket_id and b.deduplicated
    c = s.create_ticket(phone="0902", intent="refund", call_id="c3", now=NOW + 7200)
    assert c.ticket_id != a.ticket_id

def test_dedup_call_id_phone():
    s = svc()
    a = s.create_ticket(phone="0903", intent="order_status", call_id="callX", now=NOW)
    b = s.create_ticket(phone="0903", intent="other_intent", call_id="callX", now=NOW + 5)
    assert b.ticket_id == a.ticket_id

def test_completed_ticket_not_deduped_against_new_request():
    s = svc()
    a = s.create_ticket(phone="0904", intent="order_status", call_id="c1", now=NOW)
    s.complete_ticket(a.ticket_id)
    b = s.create_ticket(phone="0904", intent="order_status", call_id="c2", now=NOW + 5)
    assert b.ticket_id != a.ticket_id

def test_handoff_package_attached_and_returning_caller_resumes():
    s = svc()
    hp = {"summary": "khieu nai giao cham", "intent": "complaint"}
    t = s.create_ticket(phone="0905", intent="complaint", summary="Giao cham", handoff_package=hp, now=NOW)
    assert s.get_ticket(t.ticket_id).handoff_package == hp
    again = s.find_open_ticket("0905", "complaint", now=NOW + 100)
    assert again and again.ticket_id == t.ticket_id

def test_sla_by_priority_and_overdue_alert():
    s = svc()
    hi = s.create_ticket(phone="0911", intent="complaint", priority="critical", now=NOW)
    lo = s.create_ticket(phone="0912", intent="faq", priority="low", now=NOW)
    assert hi.sla_deadline == NOW + SLA_HOURS["critical"] * 3600
    overdue = s.overdue_tickets(now=NOW + 2 * 3600)
    assert [t.ticket_code for t in overdue] == [hi.ticket_code]
    assert s.sla_alerts(now=NOW + 2 * 3600)[0]["priority"] == "critical"

def test_scheduler_respects_window_and_capacity_and_no_duplicate_claim():
    s = svc()
    s.create_ticket(phone="0921", intent="a", window_start=NOW + 3600, window_end=NOW + 7200, now=NOW)
    due = s.create_ticket(phone="0922", intent="b", window_start=NOW - 10, window_end=NOW + 3600, now=NOW)
    assert [t.ticket_id for t in s.due_tickets(now=NOW, capacity=10)] == [due.ticket_id]
    claimed = s.claim_next(now=NOW + 3600, capacity=1)
    assert len(claimed) == 1
    claimed2 = s.claim_next(now=NOW + 3600, capacity=10)
    assert claimed[0].ticket_id not in [t.ticket_id for t in claimed2]

def test_outbox_retry_backoff_then_dead_letter():
    s = CallbackTicketService(dedup_window_s=3600, max_attempts=3, backoff_base_s=10)
    t = s.create_ticket(phone="0931", intent="order_status", now=NOW)
    def boom(payload): raise RuntimeError("CRM down")
    assert s.drain_outbox(boom, now=NOW)["failed"] == 1
    assert s.drain_outbox(boom, now=NOW + 5)["failed"] == 0
    assert s.drain_outbox(boom, now=NOW + 10)["failed"] == 1
    assert s.drain_outbox(boom, now=NOW + 100)["dead_letter"] == 1
    assert s.get_ticket(t.ticket_id).status == TicketStatus.DEAD_LETTER
    assert s.count_outbox("dead-letter") == 1
    assert s.backoff_seconds(1) == 10 and s.backoff_seconds(3) == 40

def test_outbox_success_marks_sent():
    s = svc(); s.create_ticket(phone="0932", intent="faq", now=NOW)
    seen = []
    r = s.drain_outbox(lambda p: seen.append(p), now=NOW)
    assert r["sent"] == 1 and seen and seen[0]["ticket_code"].startswith("CB")
    assert seen[0]["contracts_version"]
    assert s.count_outbox("sent") == 1 and s.count_outbox("pending") == 0

def test_fail_ticket_reschedules_then_dead_letters():
    s = CallbackTicketService(max_attempts=2, backoff_base_s=5)
    t = s.create_ticket(phone="0933", intent="callback", now=NOW)
    s.claim_next(now=NOW, capacity=1)
    f = s.fail_ticket(t.ticket_id, now=NOW)
    assert f.status == TicketStatus.FAILED and f.attempts == 1 and f.next_attempt_at == NOW + 5
    f2 = s.fail_ticket(t.ticket_id, now=NOW + 5)
    assert f2.status == TicketStatus.DEAD_LETTER and f2.attempts == 2

def test_confirmation_message_has_code_summary_and_no_dead_end():
    s = svc()
    t = s.create_ticket(phone="0934", intent="order_status", summary="Kiem tra don DH99",
                        window_start=NOW + 3600, now=NOW, confirm_channels=["sms"])
    msg = s.confirmation_message(t)
    assert t.ticket_code in msg and "DH99" in msg and "0934" in msg
    assert t.status == TicketStatus.SCHEDULED and t.confirmations_sent == ["sms"]

def test_concurrent_same_key_creates_one_ticket():
    import threading
    s = svc(); results = []
    def make(): results.append(s.create_ticket(phone="0935", intent="x", call_id="cc", idempotency_key="race", now=NOW).ticket_id)
    threads = [threading.Thread(target=make) for _ in range(8)]
    [th.start() for th in threads]; [th.join() for th in threads]
    assert len(set(results)) == 1 and s.count_tickets() == 1
