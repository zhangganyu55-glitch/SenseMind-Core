"""SQLite storage: telemetry, rule events, alerts, investigations, audits."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .clock import utc
from .models import Telemetry


TELEMETRY_COLUMNS = (
    ("received_at", "TEXT"),
    # Existing rows have no trustworthy server receipt time.  Mark them as an
    # estimate rather than pretending the sample timestamp was a receipt time.
    ("received_at_source", "TEXT NOT NULL DEFAULT 'legacy_estimated'"),
)

EVENT_COLUMNS = (
    ("source_started_at", "TEXT"),
    ("acknowledged_at", "TEXT"),
    ("acknowledged_by", "TEXT"),
    ("notification_status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("notification_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("last_notification_at", "TEXT"),
    ("last_notification_error", "TEXT"),
)

INVESTIGATION_COLUMNS = (
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("max_attempts", "INTEGER"),
    ("duplicate_of_event_id", "TEXT"),
    ("structured_json", "TEXT"),
    ("usage_json", "TEXT"),
    ("evidence_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_error_code", "TEXT"),
    ("deadline_at", "TEXT"),
)


class Storage:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self._setup()

    def _db(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _setup(self):
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                received_at TEXT,
                received_at_source TEXT NOT NULL DEFAULT 'legacy_estimated',
                data_json TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_telemetry_device ON telemetry(device_id, id DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_telemetry_time ON telemetry(device_id, timestamp)")
            con.execute("""CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                kind TEXT NOT NULL, status TEXT NOT NULL,
                opened_at TEXT NOT NULL, closed_at TEXT,
                source_started_at TEXT,
                acknowledged INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL,
                acknowledged_at TEXT, acknowledged_by TEXT,
                notification_status TEXT NOT NULL DEFAULT 'pending',
                notification_attempts INTEGER NOT NULL DEFAULT 0,
                last_notification_at TEXT, last_notification_error TEXT)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_events_device ON events(device_id, opened_at DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS assistant_runs (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL, created_at TEXT NOT NULL,
                mode TEXT NOT NULL, model TEXT, error_code TEXT,
                tools_json TEXT NOT NULL, usage_json TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS event_notifications (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL, kind TEXT NOT NULL,
                channel TEXT NOT NULL, text TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_notifications_device "
                        "ON event_notifications(device_id, created_at DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, ai_status TEXT NOT NULL,
                model TEXT, report_json TEXT, error TEXT,
                created_at TEXT NOT NULL, started_at TEXT,
                completed_at TEXT, updated_at TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_investigations_device "
                        "ON investigations(device_id, created_at DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS ml_inferences (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                window_start TEXT NOT NULL, window_end TEXT,
                dataset TEXT, participant_id TEXT, sampling_hz REAL,
                activity_label TEXT, activity_confidence REAL,
                signal_reliability REAL, anomaly_score REAL,
                model_version TEXT, result_json TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_ml_device "
                        "ON ml_inferences(device_id, created_at DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                device_id TEXT NOT NULL, source_type TEXT NOT NULL,
                timestamp TEXT, value_json TEXT, unit TEXT,
                quality_status TEXT NOT NULL, data_mode TEXT NOT NULL,
                model_version TEXT, clock_uncertainty_ms INTEGER,
                time_sync_status TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0,
                source_ref TEXT NOT NULL, metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_id, source_ref))""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_evidence_event "
                        "ON evidence(event_id, timestamp)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_evidence_device "
                        "ON evidence(device_id, timestamp DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS investigation_transitions (
                id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL,
                from_status TEXT, to_status TEXT NOT NULL,
                reason TEXT, created_at TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_transitions_investigation "
                        "ON investigation_transitions(investigation_id, created_at)")
            con.execute("""CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                event_id TEXT,
                investigation_id TEXT,
                decision_type TEXT NOT NULL,
                source TEXT NOT NULL,
                basis_json TEXT NOT NULL,
                data_quality TEXT NOT NULL,
                data_mode TEXT NOT NULL,
                decided_at TEXT NOT NULL,
                status TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                summary TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                dedup_key TEXT NOT NULL UNIQUE,
                seen_count INTEGER NOT NULL DEFAULT 1,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_decisions_device "
                        "ON decisions(device_id, decided_at DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_decisions_type "
                        "ON decisions(decision_type, decided_at DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_decisions_event "
                        "ON decisions(event_id)")
            con.execute("""CREATE TABLE IF NOT EXISTS device_monitoring (
                device_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                reason TEXT,
                last_seen_at TEXT,
                last_valid_at TEXT,
                updated_at TEXT NOT NULL)""")

            columns = {row["name"] for row in con.execute("PRAGMA table_info(telemetry)")}
            for name, definition in TELEMETRY_COLUMNS:
                if name not in columns:
                    try:
                        con.execute(f"ALTER TABLE telemetry ADD COLUMN {name} {definition}")
                    except sqlite3.OperationalError:
                        pass

            columns = {row["name"] for row in con.execute("PRAGMA table_info(events)")}
            for name, definition in EVENT_COLUMNS:
                if name not in columns:
                    try:
                        con.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")
                    except sqlite3.OperationalError:
                        pass
            columns = {row["name"] for row in con.execute("PRAGMA table_info(investigations)")}
            for name, definition in INVESTIGATION_COLUMNS:
                if name not in columns:
                    try:
                        con.execute(f"ALTER TABLE investigations ADD COLUMN {name} {definition}")
                    except sqlite3.OperationalError:
                        pass

    # -- assistant audit ---------------------------------------------------
    def log_assistant_run(self, request_id, device_id, mode, model, error_code, tools, usage):
        # Audit metadata only: do not persist prompts, model prose, reasoning or credentials.
        with self.lock, self._db() as con:
            con.execute("""INSERT INTO assistant_runs
                (id,device_id,created_at,mode,model,error_code,tools_json,usage_json)
                VALUES (?,?,?,?,?,?,?,?)""", (
                request_id, device_id, datetime.now(timezone.utc).isoformat(), mode,
                model, error_code, json.dumps(tools), json.dumps(usage),
            ))

    # -- telemetry ---------------------------------------------------------
    def put_telemetry(self, data: Telemetry, *, received_at: datetime | None = None):
        """Persist a sample.

        ``received_at`` must be supplied by server ingestion paths.  A missing
        value is explicitly marked ``legacy_estimated`` and is never presented
        as a real server receipt time.  This keeps old/direct database writes
        honest during migration.
        """
        if received_at is None:
            received_text = None
            source = "legacy_estimated"
        else:
            received_text = utc(received_at).isoformat()
            source = "server"
        with self.lock, self._db() as con:
            con.execute(
                "INSERT INTO telemetry(device_id,timestamp,received_at,"
                "received_at_source,data_json) VALUES (?,?,?,?,?)",
                (data.device_id, data.timestamp.isoformat(), received_text,
                 source, data.model_dump_json()))

    def latest(self, device_id: str, *, with_receipt: bool = False):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT data_json,received_at,received_at_source FROM telemetry "
                "WHERE device_id=? ORDER BY id DESC LIMIT 1",
                (device_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row["data_json"])
            if with_receipt:
                data["_received_at"] = row["received_at"]
                data["_received_at_source"] = row["received_at_source"]
            return data

    def history(self, device_id: str, limit: int = 20):
        with self.lock, self._db() as con:
            rows = con.execute("SELECT data_json FROM telemetry WHERE device_id=? ORDER BY id DESC LIMIT ?", (device_id, limit)).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]

    def telemetry_between(self, device_id: str, start: datetime, end: datetime,
                          limit: int = 2000, *, with_receipt: bool = False):
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT data_json,received_at,received_at_source FROM telemetry "
                "WHERE device_id=? AND timestamp>=? AND timestamp<? "
                "ORDER BY timestamp ASC LIMIT ?",
                (device_id, start.isoformat(), end.isoformat(), limit),
            ).fetchall()
            result = []
            for row in rows:
                data = json.loads(row["data_json"])
                if with_receipt:
                    data["_received_at"] = row["received_at"]
                    data["_received_at_source"] = row["received_at_source"]
                result.append(data)
            return result

    def all_device_ids(self) -> list[str]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT device_id FROM telemetry UNION SELECT device_id FROM events ORDER BY 1"
            ).fetchall()
            return [row["device_id"] for row in rows]

    # -- rule events -------------------------------------------------------
    @staticmethod
    def _event_dict(row) -> dict:
        data = dict(row)
        data["acknowledged"] = bool(data.get("acknowledged"))
        return data

    def event_open(self, device_id: str, kind: str, timestamp: datetime, note: str,
                   *, source_started_at: datetime | None = None):
        """Open an event using the server UTC lifecycle timestamp.

        ``source_started_at`` keeps the original sample-time start for baseline
        and evidence calculations; it is never used as ``opened_at``.
        """
        opened = utc(timestamp).isoformat()
        started = utc(source_started_at).isoformat() if source_started_at is not None else None
        with self.lock, self._db() as con:
            row = con.execute("SELECT * FROM events WHERE device_id=? AND kind=? AND status='active' LIMIT 1", (device_id, kind)).fetchone()
            if row:
                return None
            event_id = str(uuid4())
            con.execute(
                "INSERT INTO events (id, device_id, kind, status, opened_at, "
                "source_started_at, note) VALUES (?,?,?,?,?,?,?)",
                (event_id, device_id, kind, "active", opened, started, note))
            return {"event_id": event_id, "device_id": device_id, "kind": kind, "action": "opened"}

    def event_close(self, device_id: str, kind: str, timestamp: datetime):
        with self.lock, self._db() as con:
            row = con.execute("SELECT id FROM events WHERE device_id=? AND kind=? AND status='active' LIMIT 1", (device_id, kind)).fetchone()
            if not row:
                return None
            event_id = row[0]
            con.execute("UPDATE events SET status='resolved',closed_at=? WHERE id=?",
                        (utc(timestamp).isoformat(), event_id))
            return {"event_id": event_id, "device_id": device_id, "kind": kind, "action": "resolved"}

    def events(self, device_id: str, limit: int = 20, active_only: bool = False):
        sql = "SELECT * FROM events WHERE device_id=?" + (" AND status='active'" if active_only else "") + " ORDER BY opened_at DESC LIMIT ?"
        with self.lock, self._db() as con:
            rows = con.execute(sql, (device_id, limit)).fetchall()
            return [self._event_dict(row) for row in rows]

    def recent_events(self, limit: int = 50, device_id: str | None = None):
        with self.lock, self._db() as con:
            if device_id:
                rows = con.execute(
                    "SELECT * FROM events WHERE device_id=? ORDER BY opened_at DESC LIMIT ?",
                    (device_id, limit)).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM events ORDER BY opened_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._event_dict(row) for row in rows]

    def get_event(self, event_id: str):
        with self.lock, self._db() as con:
            row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return self._event_dict(row) if row else None

    def similar_events(self, device_id: str, kind: str, start: datetime,
                       end: datetime, exclude_id: str, limit: int = 20) -> list[dict]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM events WHERE device_id=? AND kind=? AND opened_at>=? "
                "AND opened_at<? AND id<>? ORDER BY opened_at DESC LIMIT ?",
                (device_id, kind, start.isoformat(), end.isoformat(), exclude_id, limit),
            ).fetchall()
            return [self._event_dict(row) for row in rows]

    def acknowledge(self, event_id: str, actor: str = "local_operator"):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._db() as con:
            row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if not row:
                return None
            if row["acknowledged_at"]:
                return {"acknowledged": True, "event_id": event_id,
                        "acknowledged_at": row["acknowledged_at"],
                        "acknowledged_by": row["acknowledged_by"],
                        "already_acknowledged": True}
            updated = con.execute(
                "UPDATE events SET acknowledged=1, acknowledged_at=?, acknowledged_by=? "
                "WHERE id=? AND acknowledged_at IS NULL", (now, actor, event_id))
            if updated.rowcount != 1:
                row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                return {"acknowledged": True, "event_id": event_id,
                        "acknowledged_at": row["acknowledged_at"],
                        "acknowledged_by": row["acknowledged_by"],
                        "already_acknowledged": True}
            return {"acknowledged": True, "event_id": event_id, "acknowledged_at": now,
                    "acknowledged_by": actor, "already_acknowledged": False}

    # -- notifications -----------------------------------------------------
    def create_notification(self, event: dict, text: str, cooldown_seconds: int = 300):
        """Create one notification per event, suppressing rapid repeats per device/kind."""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        cutoff = (now - timedelta(seconds=cooldown_seconds)).isoformat()
        with self.lock, self._db() as con:
            existing = con.execute(
                "SELECT * FROM event_notifications WHERE event_id=?", (event["id"],)
            ).fetchone()
            if existing:
                return dict(existing), False
            duplicate = con.execute(
                "SELECT 1 FROM event_notifications WHERE device_id=? AND kind=? "
                "AND created_at>=? LIMIT 1",
                (event["device_id"], event["kind"], cutoff),
            ).fetchone()
            status = "suppressed_duplicate" if duplicate else "pending"
            error = ("Duplicate event within notification cooldown; suppressed"
                     if duplicate else None)
            notification_id = str(uuid4())
            con.execute(
                "INSERT INTO event_notifications(id,event_id,device_id,kind,channel,text,"
                "status,attempts,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (notification_id, event["id"], event["device_id"], event["kind"],
                 "websocket_console", text, status, 0, error, now_text, now_text),
            )
            con.execute(
                "UPDATE events SET notification_status=?,notification_attempts=0,"
                "last_notification_at=?,last_notification_error=? WHERE id=?",
                (status, now_text, error, event["id"]),
            )
            row = con.execute(
                "SELECT * FROM event_notifications WHERE id=?", (notification_id,)
            ).fetchone()
            return dict(row), True

    def pending_notifications(self, device_id: str | None = None, limit: int = 50):
        sql = "SELECT * FROM event_notifications WHERE status='pending'"
        params = []
        if device_id:
            sql += " AND device_id=?"
            params.append(device_id)
        sql += " ORDER BY created_at LIMIT ?"
        params.append(limit)
        with self.lock, self._db() as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    def _finish_notifications(self, ids: list[str], status: str, error: str | None):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._db() as con:
            for notification_id in ids:
                row = con.execute(
                    "SELECT event_id FROM event_notifications WHERE id=?", (notification_id,)
                ).fetchone()
                if not row:
                    continue
                updated = con.execute(
                    "UPDATE event_notifications SET status=?,attempts=attempts+1,error=?,"
                    "updated_at=? WHERE id=? AND status='pending'",
                    (status, error, now, notification_id),
                )
                if updated.rowcount != 1:
                    continue  # another path already sent/expired it
                con.execute(
                    "UPDATE events SET notification_status=?,notification_attempts="
                    "notification_attempts+1,last_notification_at=?,last_notification_error=? "
                    "WHERE id=?",
                    (status, now, error, row["event_id"]),
                )

    def mark_notifications_sent(self, ids: list[str]):
        self._finish_notifications(ids, "sent", None)

    def mark_notifications_failed(self, ids: list[str], error: str):
        self._finish_notifications(ids, "failed", error[:200])

    def expire_pending_notifications(self, ttl_seconds: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).isoformat()
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT id FROM event_notifications WHERE status='pending' AND created_at<=?",
                (cutoff,),
            ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            self.mark_notifications_failed(ids, "No console delivered within the notification TTL")
        return len(ids)

    def notifications_for(self, event_id: str) -> list[dict]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM event_notifications WHERE event_id=? ORDER BY created_at",
                (event_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_notifications(self, limit: int = 20, device_id: str | None = None):
        sql = "SELECT * FROM event_notifications"
        params = []
        if device_id:
            sql += " WHERE device_id=?"
            params.append(device_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.lock, self._db() as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    # -- investigations ----------------------------------------------------
    def create_investigation(self, event_id: str, device_id: str, kind: str):
        now = datetime.now(timezone.utc).isoformat()
        investigation_id = str(uuid4())
        with self.lock, self._db() as con:
            created = con.execute(
                "INSERT OR IGNORE INTO investigations(id,event_id,device_id,kind,status,"
                "ai_status,created_at,updated_at) VALUES(?,?,?,?,'queued','pending',?,?)",
                (investigation_id, event_id, device_id, kind, now, now),
            )
            row = con.execute(
                "SELECT * FROM investigations WHERE event_id=?", (event_id,)
            ).fetchone()
            return dict(row), created.rowcount == 1

    def update_investigation(self, investigation_id: str, *, status: str | None = None,
                             ai_status: str | None = None, model: str | None = None,
                             report: dict | None = None, error: str | None = None,
                             started: bool = False, completed: bool = False,
                             attempts: int | None = None, max_attempts: int | None = None,
                             duplicate_of: str | None = None,
                             structured: dict | None = None, usage: dict | None = None,
                             evidence_count: int | None = None,
                             last_error_code: str | None = None,
                             deadline_at: str | None = None):
        now = datetime.now(timezone.utc).isoformat()
        sets, params = ["updated_at=?"], [now]
        if status is not None:
            sets.append("status=?"); params.append(status)
        if ai_status is not None:
            sets.append("ai_status=?"); params.append(ai_status)
        if model is not None:
            sets.append("model=?"); params.append(model)
        if report is not None:
            sets.append("report_json=?"); params.append(json.dumps(report, ensure_ascii=False))
        if error is not None:
            sets.append("error=?"); params.append(error[:300])
        if started:
            sets.append("started_at=?"); params.append(now)
        if completed:
            sets.append("completed_at=?"); params.append(now)
        if attempts is not None:
            sets.append("attempts=?"); params.append(attempts)
        if max_attempts is not None:
            sets.append("max_attempts=?"); params.append(max_attempts)
        if duplicate_of is not None:
            sets.append("duplicate_of_event_id=?"); params.append(duplicate_of)
        if structured is not None:
            sets.append("structured_json=?"); params.append(
                json.dumps(structured, ensure_ascii=False))
        if usage is not None:
            sets.append("usage_json=?"); params.append(json.dumps(usage))
        if evidence_count is not None:
            sets.append("evidence_count=?"); params.append(evidence_count)
        if last_error_code is not None:
            sets.append("last_error_code=?"); params.append(last_error_code[:120])
        if deadline_at is not None:
            sets.append("deadline_at=?"); params.append(deadline_at)
        params.append(investigation_id)
        with self.lock, self._db() as con:
            con.execute(f"UPDATE investigations SET {', '.join(sets)} WHERE id=?", params)

    def investigation_for_event(self, event_id: str):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM investigations WHERE event_id=?", (event_id,)
            ).fetchone()
            return self._investigation_dict(row) if row else None

    def investigation(self, investigation_id: str):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM investigations WHERE id=?", (investigation_id,)
            ).fetchone()
            return self._investigation_dict(row) if row else None

    def recent_investigations(self, limit: int = 20, device_id: str | None = None):
        sql = "SELECT * FROM investigations"
        params = []
        if device_id:
            sql += " WHERE device_id=?"
            params.append(device_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.lock, self._db() as con:
            return [self._investigation_dict(row)
                    for row in con.execute(sql, params).fetchall()]

    @staticmethod
    def _investigation_dict(row) -> dict:
        data = dict(row)
        data["report"] = json.loads(data.pop("report_json")) if data.get("report_json") else None
        data["structured"] = (json.loads(data.pop("structured_json"))
                              if data.get("structured_json") else None)
        data["usage"] = json.loads(data.pop("usage_json")) if data.get("usage_json") else {}
        return data

    # -- ML inferences -----------------------------------------------------
    def put_ml_inference(self, result: dict) -> str:
        inference_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._db() as con:
            con.execute(
                "INSERT INTO ml_inferences(id,device_id,window_start,window_end,dataset,"
                "participant_id,sampling_hz,activity_label,activity_confidence,"
                "signal_reliability,anomaly_score,model_version,result_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inference_id, result["device_id"], result["window_start"],
                 result.get("window_end"), result.get("dataset"),
                 result.get("participant_id"), result.get("sampling_hz"),
                 result.get("activity_label"), result.get("activity_confidence"),
                 result.get("signal_reliability"), result.get("anomaly_score"),
                 result.get("model_version"), json.dumps(result, ensure_ascii=False), now),
            )
        return inference_id

    def latest_ml_inference(self, device_id: str):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM ml_inferences WHERE device_id=? ORDER BY created_at DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            return self._ml_dict(row) if row else None

    def ml_inferences(self, device_id: str, limit: int = 20):
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM ml_inferences WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
            return [self._ml_dict(row) for row in rows]

    @staticmethod
    def _ml_dict(row) -> dict:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json"))
        return data

    # -- evidence ----------------------------------------------------------
    def put_evidence(self, data: dict) -> tuple[str, bool]:
        """Idempotent by (event_id, source_ref). First write wins."""
        event_id = data["event_id"]
        source_ref = data["source_ref"]
        timestamp = data.get("timestamp")
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        created_at = data.get("created_at") or datetime.now(timezone.utc).isoformat()
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        with self.lock, self._db() as con:
            existing = con.execute(
                "SELECT evidence_id FROM evidence WHERE event_id=? AND source_ref=?",
                (event_id, source_ref)).fetchone()
            if existing:
                return existing["evidence_id"], False
            evidence_id = data.get("evidence_id") or ("ev_" + uuid4().hex)
            con.execute(
                "INSERT INTO evidence(evidence_id,event_id,device_id,source_type,timestamp,"
                "value_json,unit,quality_status,data_mode,model_version,clock_uncertainty_ms,"
                "time_sync_status,synthetic,source_ref,metadata_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, event_id, data["device_id"], data["source_type"],
                 timestamp, json.dumps(data.get("value"), ensure_ascii=False),
                 data.get("unit"), data["quality_status"], data["data_mode"],
                 data.get("model_version"), data.get("clock_uncertainty_ms"),
                 data.get("time_sync_status", "unknown"),
                 1 if data.get("synthetic") else 0, source_ref,
                 json.dumps(data.get("metadata") or {}, ensure_ascii=False), created_at))
            return evidence_id, True

    @staticmethod
    def _evidence_dict(row) -> dict:
        data = dict(row)
        data["value"] = json.loads(data.pop("value_json"))
        data["metadata"] = json.loads(data.pop("metadata_json"))
        data["synthetic"] = bool(data.get("synthetic"))
        return data

    def evidence_for_event(self, event_id: str, limit: int = 500) -> list[dict]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM evidence WHERE event_id=? ORDER BY timestamp, created_at LIMIT ?",
                (event_id, limit)).fetchall()
            return [self._evidence_dict(row) for row in rows]

    def evidence_by_id(self, evidence_id: str) -> dict | None:
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
            return self._evidence_dict(row) if row else None

    def latest_evidence_time(self, event_id: str):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT MAX(timestamp) AS latest FROM evidence WHERE event_id=?",
                (event_id,)).fetchone()
            return (datetime.fromisoformat(row["latest"])
                    if row and row["latest"] else None)

    # -- investigation state ----------------------------------------------
    def add_investigation_transition(self, investigation_id: str, from_status: str | None,
                                     to_status: str, reason: str | None = None) -> None:
        with self.lock, self._db() as con:
            con.execute(
                "INSERT INTO investigation_transitions(id,investigation_id,from_status,"
                "to_status,reason,created_at) VALUES(?,?,?,?,?,?)",
                (str(uuid4()), investigation_id, from_status, to_status,
                 (reason or "")[:300], datetime.now(timezone.utc).isoformat()))

    def investigation_transitions(self, investigation_id: str,
                                  limit: int = 100) -> list[dict]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM investigation_transitions WHERE investigation_id=? "
                "ORDER BY created_at LIMIT ?", (investigation_id, limit)).fetchall()
            return [dict(row) for row in rows]

    def requeue_investigation(self, investigation_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._db() as con:
            con.execute(
                "UPDATE investigations SET status='queued', ai_status='pending', "
                "error=NULL, completed_at=NULL, attempts=0, updated_at=? WHERE id=?",
                (now, investigation_id))

    def incomplete_investigations(self) -> list[dict]:
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM investigations WHERE completed_at IS NULL "
                "AND status IN ('queued','running','retrying') ORDER BY created_at").fetchall()
            return [self._investigation_dict(row) for row in rows]

    # -- decisions ---------------------------------------------------------
    @staticmethod
    def _decision_dict(row) -> dict:
        data = dict(row)
        data["basis"] = (json.loads(data.pop("basis_json"))
                         if data.get("basis_json") else {})
        return data

    def put_decision(self, data: dict) -> tuple[str, bool]:
        """Idempotent by dedup_key.  Repeated evaluations increment seen_count
        instead of growing the audit log with identical rows."""
        now = datetime.now(timezone.utc).isoformat()
        decided_at = data.get("decided_at") or now
        if hasattr(decided_at, "isoformat"):
            decided_at = decided_at.isoformat()
        with self.lock, self._db() as con:
            existing = con.execute(
                "SELECT decision_id FROM decisions WHERE dedup_key=?",
                (data["dedup_key"],)).fetchone()
            if existing:
                con.execute(
                    "UPDATE decisions SET seen_count=seen_count+1, last_seen_at=?, "
                    "updated_at=? WHERE decision_id=?",
                    (now, now, existing["decision_id"]))
                return existing["decision_id"], False
            decision_id = data.get("decision_id") or ("dec_" + uuid4().hex)
            try:
                con.execute(
                    "INSERT INTO decisions(decision_id,device_id,event_id,investigation_id,"
                    "decision_type,source,basis_json,data_quality,data_mode,decided_at,status,"
                    "reason_code,summary,policy_version,dedup_key,seen_count,last_seen_at,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                    (decision_id, data["device_id"], data.get("event_id"),
                     data.get("investigation_id"), data["decision_type"], data["source"],
                     json.dumps(data.get("basis") or {}, ensure_ascii=False),
                     data["data_quality"], data["data_mode"], decided_at,
                     data["status"], data["reason_code"], data["summary"],
                     data["policy_version"], data["dedup_key"], now, now, now))
            except sqlite3.IntegrityError:
                # Cross-process race on the same dedup_key: first writer wins.
                row = con.execute(
                    "SELECT decision_id FROM decisions WHERE dedup_key=?",
                    (data["dedup_key"],)).fetchone()
                if row is None:
                    raise
                con.execute(
                    "UPDATE decisions SET seen_count=seen_count+1, last_seen_at=?, "
                    "updated_at=? WHERE decision_id=?",
                    (now, now, row["decision_id"]))
                return row["decision_id"], False
            return decision_id, True

    def update_decision(self, decision_id: str, *, status: str | None = None,
                        event_id: str | None = None,
                        investigation_id: str | None = None,
                        summary: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        sets, params = ["updated_at=?"], [now]
        if status is not None:
            sets.append("status=?"); params.append(status)
        if event_id is not None:
            sets.append("event_id=?"); params.append(event_id)
        if investigation_id is not None:
            sets.append("investigation_id=?"); params.append(investigation_id)
        if summary is not None:
            sets.append("summary=?"); params.append(summary[:600])
        params.append(decision_id)
        with self.lock, self._db() as con:
            con.execute(f"UPDATE decisions SET {', '.join(sets)} WHERE decision_id=?",
                        params)

    def decision(self, decision_id: str):
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            return self._decision_dict(row) if row else None

    def decisions(self, device_id: str | None = None, limit: int = 50,
                  decision_type: str | None = None):
        sql = "SELECT * FROM decisions"
        clauses, params = [], []
        if device_id:
            clauses.append("device_id=?"); params.append(device_id)
        if decision_type:
            clauses.append("decision_type=?"); params.append(decision_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY decided_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self.lock, self._db() as con:
            rows = con.execute(sql, params).fetchall()
            return [self._decision_dict(row) for row in rows]

    def decisions_for_event(self, event_id: str, limit: int = 50):
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM decisions WHERE event_id=? "
                "ORDER BY decided_at ASC, created_at ASC LIMIT ?",
                (event_id, limit)).fetchall()
            return [self._decision_dict(row) for row in rows]

    def latest_decision(self, device_id: str, decision_type: str | None = None):
        sql = "SELECT * FROM decisions WHERE device_id=?"
        params = [device_id]
        if decision_type:
            sql += " AND decision_type=?"
            params.append(decision_type)
        sql += " ORDER BY decided_at DESC, created_at DESC LIMIT 1"
        with self.lock, self._db() as con:
            row = con.execute(sql, params).fetchone()
            return self._decision_dict(row) if row else None

    # -- monitoring state --------------------------------------------------
    def update_monitoring(self, device_id: str, *, state: str,
                          reason: str | None = None,
                          last_seen_at=None, last_valid_at=None) -> dict:
        now = datetime.now(timezone.utc).isoformat()

        def text(value):
            if value is None:
                return None
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        seen = text(last_seen_at)
        valid = text(last_valid_at)
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM device_monitoring WHERE device_id=?",
                (device_id,)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO device_monitoring(device_id,state,reason,"
                    "last_seen_at,last_valid_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (device_id, state, reason, seen, valid, now))
            else:
                # Never rewind the last-seen/last-valid clocks on late data.
                if row["last_seen_at"] and (seen is None or seen < row["last_seen_at"]):
                    seen = row["last_seen_at"]
                if row["last_valid_at"] and (valid is None or valid < row["last_valid_at"]):
                    valid = row["last_valid_at"]
                con.execute(
                    "UPDATE device_monitoring SET state=?,reason=?,"
                    "last_seen_at=?,last_valid_at=?,updated_at=? "
                    "WHERE device_id=?",
                    (state, reason, seen, valid, now, device_id))
            current = con.execute(
                "SELECT * FROM device_monitoring WHERE device_id=?",
                (device_id,)).fetchone()
            return dict(current)

    def monitoring(self, device_id: str, now: datetime | None = None,
                   stale_seconds: float = 30.0) -> dict:
        """Return the stored state, deriving STALE when the last sample is old."""
        with self.lock, self._db() as con:
            row = con.execute(
                "SELECT * FROM device_monitoring WHERE device_id=?",
                (device_id,)).fetchone()
        if row is None:
            return {"device_id": device_id, "state": "NO_DATA",
                    "reason": "no_telemetry", "last_seen_at": None,
                    "last_valid_at": None, "updated_at": None,
                    "derived": False}
        data = dict(row)
        data["derived"] = False
        moment = now or datetime.now(timezone.utc)
        if data.get("last_seen_at"):
            try:
                seen = datetime.fromisoformat(data["last_seen_at"])
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                age = (moment - seen).total_seconds()
                if age > stale_seconds:
                    data["state"] = "STALE"
                    data["reason"] = "no_recent_data"
                    data["derived"] = True
            except ValueError:
                pass
        return data

    def events_by_activity(self, device_id: str, kind: str, start: datetime,
                           end: datetime, limit: int = 1) -> list[dict]:
        """Events whose last activity (close, else open) falls in the window.

        Used by Decision Engine cooldown so a long-running event cannot make
        its cooldown expire simply because it opened long ago.
        """
        with self.lock, self._db() as con:
            rows = con.execute(
                "SELECT * FROM events WHERE device_id=? AND kind=? "
                "AND COALESCE(closed_at, opened_at)>=? "
                "AND COALESCE(closed_at, opened_at)<? "
                "ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?",
                (device_id, kind, start.isoformat(), end.isoformat(), limit),
            ).fetchall()
            return [self._event_dict(row) for row in rows]

    def delete_device_data(self, device_id: str) -> None:
        """Remove everything this prototype holds for one device (APK data deletion)."""
        with self.lock, self._db() as con:
            con.execute("DELETE FROM device_monitoring WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM decisions WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM evidence WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM investigation_transitions WHERE investigation_id IN "
                        "(SELECT id FROM investigations WHERE device_id=?)", (device_id,))
            con.execute("DELETE FROM ml_inferences WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM event_notifications WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM investigations WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM telemetry WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM events WHERE device_id=?", (device_id,))
            con.execute("DELETE FROM assistant_runs WHERE device_id=?", (device_id,))
