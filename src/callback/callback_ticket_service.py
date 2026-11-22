 — phần 1/3
"""
Callback / ticket service - durable, never lose a request.

Outbox pattern on SQLite (stdlib only):
  ticket row + outbox event are written in ONE transaction - either both
  exist or neither does. A worker drains the outbox to CRM/helpdesk with
  exponential backoff; after max_attempts the event goes to dead-letter
  and the ticket is flagged, never silently dropped.

Idempotency & dedup (unique indexes + a lock, safe under concurrency):
  * same idempotency_key -> same ticket, no duplicate, no 2nd event
  * same (call_id, phone) -> same open ticket
  * same (phone, intent) inside the dedup window -> same open ticket
    (a returning caller resumes the old ticket)

Scheduler respects the customer-chosen time window and team capacity,
and claims tickets atomically (queued/scheduled -> calling).

States: queued / scheduled / calling / completed / failed / dead-letter
CONTRACTS_VERSION / EscalationReason are imported from src.contracts
(locked v1.0.0) and stamped into every outbox payload; NO mirror here.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from src.contracts import CONTRACTS_VERSION, EscalationReason  # type: ignore


class TicketStatus(str, Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    CALLING = "calling"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead-letter"


DEAD_LETTER = TicketStatus.DEAD_LETTER
OPEN_STATUSES = {TicketStatus.QUEUED, TicketStatus.SCHEDULED,
                 TicketStatus.CALLING, TicketStatus.FAILED}

SLA_HOURS = {"critical": 1, "high": 4, "normal": 24, "low": 48}
_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


@dataclass
class CallbackTicket:
    ticket_id: int = 0
    ticket_code: str = ""
    tenant_id: str = ""
    call_id: str = ""
    phone: str = ""
    intent: str = ""
    summary: str = ""
    transcript: str = ""
    handoff_package: Any = None
    priority: str = "normal"
    status: TicketStatus = TicketStatus.QUEUED
    idempotency_key: str = ""
    attempts: int = 0
    max_attempts: int = 3
    window_start: Optional[float] = None
    window_end: Optional[float] = None
    created_at: float = 0.0
    sla_deadline: float = 0.0
    next_attempt_at: Optional[float] = None
    confirmations_sent: list = field(default_factory=list)
    deduplicated: bool = False

    @property
    def id(self) -> int:
        return self.ticket_id

    def is_overdue(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self.status not in (TicketStatus.COMPLETED,
                                   TicketStatus.DEAD_LETTER) \
            and bool(self.sla_deadline) and now > self.sla_deadline


class CallbackTicketService:
    def __init__(self, db_path: str = ":memory:",
                 dedup_window_s: float = 86400.0, max_attempts: int = 3,
                 backoff_base_s: float = 60.0):
        self.db_path = db_path
        self.dedup_window_s = float(dedup_window_s)
        self.max_attempts = int(max_attempts)
        self.backoff_base_s = float(backoff_base_s)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tickets(
              ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticket_code TEXT UNIQUE, tenant_id TEXT, call_id TEXT,
              phone TEXT, intent TEXT, summary TEXT, transcript TEXT,
              handoff TEXT, priority TEXT, status TEXT,
              idempotency_key TEXT UNIQUE, attempts INTEGER,
              max_attempts INTEGER, window_start REAL, window_end REAL,
              created_at REAL, sla_deadline REAL, next_attempt_at REAL,
              confirmations TEXT);
            CREATE INDEX IF NOT EXISTS ix_tickets_phone_intent
              ON tickets(phone, intent, created_at);
            CREATE INDEX IF NOT EXISTS ix_tickets_call_phone
              ON tickets(call_id, phone);
            CREATE TABLE IF NOT EXISTS outbox(
              event_id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticket_id INTEGER, event_type TEXT, payload TEXT,
              status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
              next_retry_at REAL, created_at REAL);
            """)



[[FILE src/callback/callback_ticket_service.py]] — phần 2/3 (nối tiếp)

    # ------------------------------------------------------------- reads
    def _row_to_ticket(self, row) -> CallbackTicket:
        return CallbackTicket(
            ticket_id=row["ticket_id"], ticket_code=row["ticket_code"] or "",
            tenant_id=row["tenant_id"] or "", call_id=row["call_id"] or "",
            phone=row["phone"] or "", intent=row["intent"] or "",
            summary=row["summary"] or "", transcript=row["transcript"] or "",
            handoff_package=json.loads(row["handoff"]) if row["handoff"] else None,
            priority=row["priority"] or "normal",
            status=TicketStatus(row["status"]),
            idempotency_key=row["idempotency_key"] or "",
            attempts=row["attempts"] or 0,
            max_attempts=row["max_attempts"] or self.max_attempts,
            window_start=row["window_start"], window_end=row["window_end"],
            created_at=row["created_at"] or 0.0,
            sla_deadline=row["sla_deadline"] or 0.0,
            next_attempt_at=row["next_attempt_at"],
            confirmations_sent=json.loads(row["confirmations"] or "[]"))

    def _get(self, ticket_id: int) -> Optional[CallbackTicket]:
        row = self._db.execute("SELECT * FROM tickets WHERE ticket_id=?",
                               (ticket_id,)).fetchone()
        return self._row_to_ticket(row) if row else None

    def get_ticket(self, ticket_id: int = 0,
                   ticket_code: str = "") -> Optional[CallbackTicket]:
        with self._lock:
            if ticket_id:
                return self._get(ticket_id)
            row = self._db.execute(
                "SELECT * FROM tickets WHERE ticket_code=?",
                (ticket_code,)).fetchone()
            return self._row_to_ticket(row) if row else None

    def count_tickets(self) -> int:
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) c FROM tickets").fetchone()["c"]

    def count_outbox(self, status: Optional[str] = None) -> int:
        with self._lock:
            if status:
                return self._db.execute(
                    "SELECT COUNT(*) c FROM outbox WHERE status=?",
                    (status,)).fetchone()["c"]
            return self._db.execute(
                "SELECT COUNT(*) c FROM outbox").fetchone()["c"]

    # ------------------------------------------------------------ create
    def _find_duplicate(self, *, phone, intent, call_id, idempotency_key, now):
        if idempotency_key:
            row = self._db.execute(
                "SELECT * FROM tickets WHERE idempotency_key=?",
                (idempotency_key,)).fetchone()
            if row:
                return self._row_to_ticket(row)
        if call_id and phone:
            row = self._db.execute(
                "SELECT * FROM tickets WHERE call_id=? AND phone=? "
                "ORDER BY ticket_id DESC", (call_id, phone)).fetchone()
            if row and TicketStatus(row["status"]) in OPEN_STATUSES:
                return self._row_to_ticket(row)
        if phone and intent:
            row = self._db.execute(
                "SELECT * FROM tickets WHERE phone=? AND intent=? "
                "AND created_at>=? ORDER BY ticket_id DESC",
                (phone, intent, now - self.dedup_window_s)).fetchone()
            if row and TicketStatus(row["status"]) in OPEN_STATUSES:
                return self._row_to_ticket(row)
        return None

    def create_ticket(self, *, phone: str, intent: str = "", summary: str = "",
                      transcript: str = "", call_id: str = "",
                      tenant_id: str = "", idempotency_key: str = "",
                      priority: str = "normal", handoff_package: Any = None,
                      window_start: Optional[float] = None,
                      window_end: Optional[float] = None,
                      now: Optional[float] = None,
                      confirm_channels: Optional[list] = None) -> CallbackTicket:
        """Create ticket + outbox event atomically, or return duplicate."""
        now = time.time() if now is None else float(now)
        priority = priority if priority in SLA_HOURS else "normal"
        if not idempotency_key:
            idempotency_key = f"{call_id}:{phone}" if call_id else uuid.uuid4().hex
        with self._lock:
            dup = self._find_duplicate(
                phone=phone, intent=intent, call_id=call_id,
                idempotency_key=idempotency_key, now=now)
            if dup is not None:
                dup.deduplicated = True
                return dup
            status = TicketStatus.SCHEDULED if window_start else TicketStatus.QUEUED
            sla = now + SLA_HOURS[priority] * 3600
            confirmations = list(confirm_channels or [])
            try:
                with self._db:  # ONE transaction: ticket + outbox
                    cur = self._db.execute(
                        "INSERT INTO tickets(ticket_code,tenant_id,call_id,"
                        "phone,intent,summary,transcript,handoff,priority,"
                        "status,idempotency_key,attempts,max_attempts,"
                        "window_start,window_end,created_at,sla_deadline,"
                        "next_attempt_at,confirmations) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("", tenant_id, call_id, phone, intent, summary,
                         transcript,
                         json.dumps(handoff_package, ensure_ascii=False,
                                    default=str) if handoff_package is not None else None,
                         priority, status.value, idempotency_key, 0,
                         self.max_attempts, window_start, window_end, now,
                         sla, window_start, json.dumps(confirmations)))
                    tid = cur.lastrowid
                    code = f"CB{tid:06d}"
                    self._db.execute(
                        "UPDATE tickets SET ticket_code=? WHERE ticket_id=?",
                        (code, tid))
                    payload = {"ticket_id": tid, "ticket_code": code,
                               "phone": phone, "intent": intent,
                               "summary": summary, "priority": priority,
                               "contracts_version": CONTRACTS_VERSION,
                               "handoff_package": handoff_package}
                    self._db.execute(
                        "INSERT INTO outbox(ticket_id,event_type,payload,"
                        "status,attempts,next_retry_at,created_at) "
                        "VALUES(?,?,?,?,0,?,?)",
                        (tid, "callback_ticket_created",
                         json.dumps(payload, ensure_ascii=False, default=str),
                         "pending", now, now))
            except sqlite3.IntegrityError:
                dup = self._find_duplicate(
                    phone=phone, intent=intent, call_id=call_id,
                    idempotency_key=idempotency_key, now=now)
                if dup is not None:
                    dup.deduplicated = True
                    return dup
                raise
            ticket = self._get(tid)
            ticket.deduplicated = False
            return ticket

    create_callback = create_ticket
    create = create_ticket

    def find_open_ticket(self, phone: str, intent: str = "",
                         now: Optional[float] = None) -> Optional[CallbackTicket]:
        """A returning caller resumes their old open ticket."""
        now = time.time() if now is None else float(now)
        with self._lock:
            if intent:
                return self._find_duplicate(
                    phone=phone, intent=intent, call_id="",
                    idempotency_key="", now=now)
            row = self._db.execute(
                "SELECT * FROM tickets WHERE phone=? "
                "ORDER BY ticket_id DESC", (phone,)).fetchone()
            if row and TicketStatus(row["status"]) in OPEN_STATUSES:
                return self._row_to_ticket(row)
            return None



[[FILE src/callback/callback_ticket_service.py]] — phần 3/3 (nối tiếp, kết thúc file)

    # ------------------------------------------------------ outbox worker
    def drain_outbox(self, sender: Callable[[dict], Any],
                     now: Optional[float] = None, limit: int = 100) -> dict:
        now = time.time() if now is None else float(now)
        sent = failed = dead = 0
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM outbox WHERE status='pending' "
                "AND (next_retry_at IS NULL OR next_retry_at<=?) "
                "ORDER BY event_id LIMIT ?", (now, limit)).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                try:
                    sender(payload)
                except Exception:
                    attempts = (row["attempts"] or 0) + 1
                    if attempts >= self.max_attempts:
                        with self._db:
                            self._db.execute(
                                "UPDATE outbox SET status='dead-letter', "
                                "attempts=? WHERE event_id=?",
                                (attempts, row["event_id"]))
                            self._db.execute(
                                "UPDATE tickets SET status=? "
                                "WHERE ticket_id=? AND status!=?",
                                (TicketStatus.DEAD_LETTER.value,
                                 row["ticket_id"],
                                 TicketStatus.COMPLETED.value))
                        dead += 1
                    else:
                        nxt = now + self.backoff_base_s * (2 ** (attempts - 1))
                        with self._db:
                            self._db.execute(
                                "UPDATE outbox SET attempts=?, "
                                "next_retry_at=? WHERE event_id=?",
                                (attempts, nxt, row["event_id"]))
                        failed += 1
                else:
                    with self._db:
                        self._db.execute(
                            "UPDATE outbox SET status='sent' WHERE event_id=?",
                            (row["event_id"],))
                    sent += 1
        return {"sent": sent, "failed": failed, "dead_letter": dead}

    def backoff_seconds(self, attempts: int) -> float:
        return self.backoff_base_s * (2 ** max(0, attempts - 1))

    # ---------------------------------------------------------- scheduler
    def due_tickets(self, now: Optional[float] = None,
                    capacity: int = 1) -> list:
        now = time.time() if now is None else float(now)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM tickets WHERE status IN "
                "('queued','scheduled','failed') "
                "AND (window_start IS NULL OR window_start<=?) "
                "AND (window_end IS NULL OR window_end>=?) "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?)",
                (now, now, now)).fetchall()
            tickets = [self._row_to_ticket(r) for r in rows]
            tickets.sort(key=lambda t: (_PRIORITY_ORDER.get(t.priority, 2),
                                        t.sla_deadline, t.created_at))
            return tickets[:max(0, capacity)]

    def claim_next(self, now: Optional[float] = None,
                   capacity: int = 1) -> list:
        """Atomically move due tickets to CALLING; a second claim gets
        none of the same tickets (prevents duplicate calls)."""
        claimed = []
        with self._lock:
            for t in self.due_tickets(now=now, capacity=capacity):
                with self._db:
                    cur = self._db.execute(
                        "UPDATE tickets SET status='calling' "
                        "WHERE ticket_id=? AND status IN "
                        "('queued','scheduled','failed')", (t.ticket_id,))
                if cur.rowcount == 1:
                    t.status = TicketStatus.CALLING
                    claimed.append(t)
        return claimed

    def complete_ticket(self, ticket_id: int) -> Optional[CallbackTicket]:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE tickets SET status='completed' WHERE ticket_id=?",
                (ticket_id,))
        return self.get_ticket(ticket_id)

    def fail_ticket(self, ticket_id: int,
                    now: Optional[float] = None) -> Optional[CallbackTicket]:
        now = time.time() if now is None else float(now)
        with self._lock:
            t = self._get(ticket_id)
            if t is None:
                return None
            attempts = t.attempts + 1
            if attempts >= t.max_attempts:
                status, nxt = TicketStatus.DEAD_LETTER, None
            else:
                status = TicketStatus.FAILED
                nxt = now + self.backoff_seconds(attempts)
            with self._db:
                self._db.execute(
                    "UPDATE tickets SET status=?, attempts=?, "
                    "next_attempt_at=? WHERE ticket_id=?",
                    (status.value, attempts, nxt, ticket_id))
        return self.get_ticket(ticket_id)

    # ------------------------------------------------- SLA + confirmation
    def overdue_tickets(self, now: Optional[float] = None) -> list:
        now = time.time() if now is None else float(now)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM tickets WHERE status NOT IN "
                "('completed','dead-letter') AND sla_deadline<? "
                "ORDER BY sla_deadline", (now,)).fetchall()
            return [self._row_to_ticket(r) for r in rows]

    def sla_alerts(self, now: Optional[float] = None) -> list:
        return [{"ticket_code": t.ticket_code, "phone": t.phone,
                 "priority": t.priority, "sla_deadline": t.sla_deadline,
                 "status": t.status.value}
                for t in self.overdue_tickets(now)]

    def confirmation_message(self, ticket: CallbackTicket) -> str:
        """Read-back text the AI speaks / sends by SMS/Zalo/email."""
        window = ""
        if ticket.window_start:
            window = (" Khung giờ gọi lại bắt đầu lúc "
                      + time.strftime("%H:%M %d/%m/%Y",
                                      time.localtime(ticket.window_start))
                      + ".")
        return (f"Đã ghi nhận yêu cầu của bạn. Mã tra cứu: "
                f"{ticket.ticket_code}. Tóm tắt: "
                f"{ticket.summary or ticket.intent}.{window} "
                f"Nhân viên sẽ gọi lại số {ticket.phone} trong khung giờ "
                f"đã hẹn. Bạn không cần kể lại từ đầu.")

    def close(self) -> None:
        with self._lock:
            self._db.close()
