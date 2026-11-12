"""Agent 3: Log Analysis Agent — parses, classifies, and correlates system/app logs."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import AgentExecution, AuditLog


LOG_PATTERN = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+"
    r"(?P<level>INFO|WARNING|WARN|ERROR|CRITICAL)\s+"
    r"(?P<service>[a-zA-Z0-9_.-]+)\s+"
    r"(?P<message>.+)$"
)

SIGNATURE_PATTERNS = [
    ("CPU_THRESHOLD_EXCEEDED", re.compile(r"CPU_THRESHOLD_EXCEEDED|CPU utilization:\s*(9\d|100)%|resource exhaustion", re.I)),
    ("DISK_SPACE_CRITICAL", re.compile(r"DISK_SPACE_CRITICAL|Disk utilization:\s*(9\d|100)%|Temporary storage threshold exceeded", re.I)),
    ("SERVICE_FAILURE", re.compile(r"SERVICE_FAILURE|unavailable|HTTP 503", re.I)),
    ("DB_CONNECTION_REFUSED", re.compile(r"Connection refused|Database connection failed|connection pool exhausted", re.I)),
]


class LogAnalysisAgent:
    """Parses simulated logs, extracts ERROR/WARNING/CRITICAL events, and correlates evidence."""

    name = "Log Analysis Agent"

    def parse_line(self, line: str) -> Dict[str, Any]:
        """Parse a single log line into structured fields."""
        match = LOG_PATTERN.match(line.strip())
        if not match:
            upper = line.upper()
            level = "INFO"
            for candidate in ("CRITICAL", "ERROR", "WARNING", "WARN"):
                if candidate in upper:
                    level = "WARNING" if candidate == "WARN" else candidate
                    break
            return {
                "timestamp": "unknown",
                "level": level,
                "service": "unknown",
                "message": line.strip(),
                "raw": line.strip(),
            }
        level = match.group("level")
        if level == "WARN":
            level = "WARNING"
        return {
            "timestamp": match.group("timestamp"),
            "level": level,
            "service": match.group("service"),
            "message": match.group("message"),
            "raw": line.strip(),
        }

    def analyze(
        self,
        logs: List[str],
        affected_service: Optional[str] = None,
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Classify log entries, extract signatures, and correlate with incident context."""
        parsed = [self.parse_line(line) for line in logs if line and line.strip()]
        counts = Counter(entry["level"] for entry in parsed)

        critical_events = [e for e in parsed if e["level"] == "CRITICAL"]
        error_events = [e for e in parsed if e["level"] == "ERROR"]
        warning_events = [e for e in parsed if e["level"] == "WARNING"]
        notable_events = [e for e in parsed if e["level"] in {"CRITICAL", "ERROR", "WARNING"}]

        signatures: List[str] = []
        for sig_name, pattern in SIGNATURE_PATTERNS:
            if any(pattern.search(e["message"]) for e in notable_events):
                signatures.append(sig_name)

        correlated_services = sorted({e["service"] for e in notable_events if e["service"] != "unknown"})
        if affected_service and affected_service not in correlated_services and notable_events:
            # Check if service appears anywhere in messages
            if any(affected_service in e["message"] for e in notable_events):
                correlated_services.append(affected_service)

        related_events = [
            e
            for e in notable_events
            if not affected_service
            or e["service"] == affected_service
            or affected_service in e["message"]
            or e["level"] in {"CRITICAL", "ERROR"}
        ]

        summary = (
            f"Processed {len(parsed)} log entries: "
            f"{counts.get('CRITICAL', 0)} CRITICAL, "
            f"{counts.get('ERROR', 0)} ERROR, "
            f"{counts.get('WARNING', 0)} WARNING. "
            f"Detected signatures: {', '.join(signatures) if signatures else 'NONE'}."
        )

        report: Dict[str, Any] = {
            "agent": self.name,
            "status": "COMPLETED",
            "total_logs_processed": len(parsed),
            "counts_by_level": {
                "INFO": counts.get("INFO", 0),
                "WARNING": counts.get("WARNING", 0),
                "ERROR": counts.get("ERROR", 0),
                "CRITICAL": counts.get("CRITICAL", 0),
            },
            "critical_events": critical_events,
            "error_events": error_events,
            "warning_events": warning_events,
            "correlated_services": correlated_services,
            "error_signatures": signatures,
            "related_events": related_events,
            "summary": summary,
        }

        if db is not None and incident_id is not None:
            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name=self.name,
                    status="COMPLETED",
                    message=summary,
                    input_summary=json.dumps({"log_count": len(logs), "affected_service": affected_service}),
                    output_summary=json.dumps(
                        {
                            "counts_by_level": report["counts_by_level"],
                            "error_signatures": signatures,
                            "correlated_services": correlated_services,
                        }
                    ),
                )
            )
            db.add(
                AuditLog(
                    incident_id=incident_id,
                    actor=self.name,
                    event_type="LOGS_ANALYZED",
                    what_happened=summary,
                    evidence_json=json.dumps({"related_events": related_events, "signatures": signatures}),
                )
            )
            db.commit()

        return report
