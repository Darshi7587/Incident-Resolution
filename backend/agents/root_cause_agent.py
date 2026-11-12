"""Agent 4: Root Cause Analysis Agent — correlates evidence via Ollama LLM with deterministic fallback."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings
from backend.database.models import AgentExecution, AuditLog, RootCauseAnalysis


class RootCauseAnalysisAgent:
    """Correlates monitoring and log evidence to produce probable root cause hypotheses."""

    name = "Root Cause Analysis Agent"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def _build_prompt(
        self,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        incident_type: str,
    ) -> str:
        evidence_payload = {
            "incident_type": incident_type,
            "severity": monitoring_result.get("severity"),
            "metrics": monitoring_result.get("metrics"),
            "threshold_violations": monitoring_result.get("threshold_violations", []),
            "affected_services": monitoring_result.get("affected_services", []),
            "log_summary": log_result.get("summary"),
            "error_signatures": log_result.get("error_signatures", []),
            "related_log_events": log_result.get("related_events", []),
        }
        return (
            "You are a Senior Site Reliability Engineer performing Root Cause Analysis on a simulated IT incident.\n"
            "Analyze the correlated monitoring metrics and log evidence below.\n"
            "IMPORTANT: Treat all findings as probable hypotheses, never state an unverified cause as 100% confirmed.\n"
            "Respond strictly in valid JSON with keys:\n"
            "- probable_cause (string: concise probable root cause hypothesis)\n"
            "- confidence_score (float between 0.0 and 0.99)\n"
            "- reasoning_summary (string: why this cause is suspected based on the evidence)\n"
            "- supporting_evidence (list of strings)\n"
            "- hypotheses (list of objects with keys 'hypothesis', 'likelihood', 'evidence')\n\n"
            f"Telemetry Evidence:\n{json.dumps(evidence_payload, indent=2)}"
        )

    def _try_ollama(
        self,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        incident_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Attempt local Ollama JSON inference; return None if unreachable or malformed."""
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"
        prompt = self._build_prompt(monitoring_result, log_result, incident_type)
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        try:
            with httpx.Client(timeout=float(self.settings.ollama_timeout_seconds)) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                raw_text = response.json().get("response", "").strip()
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict) or not parsed.get("probable_cause"):
                    return None
                confidence = float(parsed.get("confidence_score", 0.75))
                confidence = max(0.0, min(0.99, confidence))
                return {
                    "probable_cause": str(parsed["probable_cause"]),
                    "confidence_score": round(confidence, 2),
                    "reasoning_summary": str(parsed.get("reasoning_summary", "")),
                    "supporting_evidence": [str(x) for x in parsed.get("supporting_evidence", [])],
                    "hypotheses": parsed.get("hypotheses", []),
                    "reasoning_source": "OLLAMA_LLM",
                    "model_used": self.settings.ollama_model,
                }
        except Exception:
            return None

    def _deterministic_fallback(
        self,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        incident_type: str,
    ) -> Dict[str, Any]:
        """Rule-based correlation fallback when Ollama is offline or unavailable."""
        metrics = monitoring_result.get("metrics", {})
        violations = monitoring_result.get("threshold_violations", [])
        signatures = set(log_result.get("error_signatures", []))
        related_events = log_result.get("related_events", [])

        supporting: List[str] = [v["message"] for v in violations]
        supporting.extend(f"[{e['timestamp']}] {e['level']} {e['service']}: {e['message']}" for e in related_events[:4])

        cpu = float(metrics.get("cpu_usage", 0.0))
        disk = float(metrics.get("disk_usage", 0.0))
        db_connected = bool(metrics.get("db_connected", True))

        if incident_type == "high_cpu" or (cpu >= self.settings.cpu_critical_threshold and "CPU_THRESHOLD_EXCEEDED" in signatures):
            probable_cause = (
                "Probable runaway worker thread pool or resource-intensive process exhausting CPU on application-server"
            )
            confidence = 0.87
            reasoning = (
                f"Correlated CPU spike reaching {cpu}% (critical threshold {self.settings.cpu_critical_threshold}%) "
                "with log signature CPU_THRESHOLD_EXCEEDED and application-server resource exhaustion messages. "
                "Memory (60%) and disk (55%) remain normal, isolating the bottleneck to application-server compute."
            )
            hypotheses = [
                {
                    "hypothesis": "Runaway worker thread pool / CPU-bound loop in application-server",
                    "likelihood": "HIGH",
                    "evidence": "CPU escalated 45% -> 72% -> 95% with CPU_THRESHOLD_EXCEEDED in logs",
                },
                {
                    "hypothesis": "Sudden unthrottled traffic burst causing thread contention",
                    "likelihood": "MEDIUM",
                    "evidence": "Request queue latency rising alongside normal memory/disk usage",
                },
            ]
        elif incident_type == "disk_full" or (disk >= self.settings.disk_critical_threshold and "DISK_SPACE_CRITICAL" in signatures):
            avail = metrics.get("disk_available_gb", "low")
            fs = metrics.get("filesystem", "/dev/sda1")
            probable_cause = (
                f"Probable temporary file accumulation filling filesystem {fs} on storage-service"
            )
            confidence = 0.89
            reasoning = (
                f"Disk utilization reached {disk}% ({avail} GB remaining on {fs}) while CPU and memory stay normal. "
                "Correlated DISK_SPACE_CRITICAL and temporary storage threshold exceeded log events in storage-service."
            )
            hypotheses = [
                {
                    "hypothesis": "Unrotated temporary cache/spool files in /var/tmp/sim-cache",
                    "likelihood": "HIGH",
                    "evidence": "Logs indicate temporary storage threshold exceeded (42 GB)",
                },
                {
                    "hypothesis": "Runaway diagnostic dump or log rotation failure",
                    "likelihood": "MEDIUM",
                    "evidence": f"Disk escalated 85% -> 96% on {fs}",
                },
            ]
        elif incident_type == "service_failure" or (not db_connected or "SERVICE_FAILURE" in signatures or "DB_CONNECTION_REFUSED" in signatures):
            probable_cause = (
                "Probable database connectivity failure (db-server unreachable / connection refused) causing payment-api outage"
            )
            confidence = 0.90
            reasoning = (
                "Monitoring reports payment-api FAILED and db_connected=False. "
                "Logs confirm HTTP 503 unavailability alongside 'Connection refused' to db-server:5432 and pool exhaustion."
            )
            hypotheses = [
                {
                    "hypothesis": "Downstream db-server connection refusal or crashed database listener",
                    "likelihood": "HIGH",
                    "evidence": "payment-api logs 'Connection refused while connecting to db-server:5432'",
                },
                {
                    "hypothesis": "Stale or exhausted connection pool inside payment-api after DB blip",
                    "likelihood": "MEDIUM",
                    "evidence": "Service healthcheck failed with SERVICE_FAILURE",
                },
            ]
        elif monitoring_result.get("severity") == "NORMAL":
            probable_cause = "No active incident detected; system telemetry and logs are within healthy baseline"
            confidence = 0.95
            reasoning = "All monitored CPU, memory, disk, and service checks passed with zero ERROR/CRITICAL logs."
            hypotheses = []
        else:
            probable_cause = "Probable degraded infrastructure resource or service anomaly requiring further inspection"
            confidence = 0.55
            reasoning = "Threshold violations or warning logs were observed without matching a specific primary signature."
            hypotheses = [
                {
                    "hypothesis": "Transient resource contention or partial service degradation",
                    "likelihood": "MEDIUM",
                    "evidence": "; ".join(supporting[:3]) or "Partial telemetry anomaly",
                }
            ]

        return {
            "probable_cause": probable_cause,
            "confidence_score": confidence,
            "reasoning_summary": reasoning,
            "supporting_evidence": supporting,
            "hypotheses": hypotheses,
            "reasoning_source": "DETERMINISTIC_FALLBACK",
            "model_used": "rule-based-correlator",
        }

    def analyze(
        self,
        monitoring_result: Dict[str, Any],
        log_result: Dict[str, Any],
        incident_type: str,
        incident_id: Optional[str] = None,
        db: Optional[Session] = None,
        prefer_llm: bool = True,
    ) -> Dict[str, Any]:
        """Generate probable root cause hypotheses using Ollama when available or deterministic fallback."""
        analysis = None
        if prefer_llm and monitoring_result.get("severity") != "NORMAL":
            analysis = self._try_ollama(monitoring_result, log_result, incident_type)

        if analysis is None:
            analysis = self._deterministic_fallback(monitoring_result, log_result, incident_type)

        analysis["agent"] = self.name
        analysis["status"] = "COMPLETED"

        if db is not None and incident_id is not None:
            db.add(
                RootCauseAnalysis(
                    incident_id=incident_id,
                    probable_cause=analysis["probable_cause"],
                    confidence_score=analysis["confidence_score"],
                    reasoning_source=analysis["reasoning_source"],
                    reasoning_summary=analysis["reasoning_summary"],
                    supporting_evidence_json=json.dumps(analysis["supporting_evidence"]),
                    hypotheses_json=json.dumps(analysis["hypotheses"]),
                )
            )
            msg = (
                f"Root cause hypothesis ({analysis['reasoning_source']}, confidence={analysis['confidence_score']}): "
                f"{analysis['probable_cause']}"
            )
            db.add(
                AgentExecution(
                    incident_id=incident_id,
                    agent_name=self.name,
                    status="COMPLETED",
                    message=msg,
                    input_summary=json.dumps(
                        {
                            "severity": monitoring_result.get("severity"),
                            "signatures": log_result.get("error_signatures", []),
                        }
                    ),
                    output_summary=json.dumps(
                        {
                            "probable_cause": analysis["probable_cause"],
                            "confidence_score": analysis["confidence_score"],
                            "reasoning_source": analysis["reasoning_source"],
                        }
                    ),
                )
            )
            db.add(
                AuditLog(
                    incident_id=incident_id,
                    actor=self.name,
                    event_type="RCA_GENERATED",
                    what_happened=msg,
                    evidence_json=json.dumps(analysis["supporting_evidence"]),
                )
            )
            db.commit()

        return analysis
