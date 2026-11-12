"""Risk Engine and allowlisted action policy evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from backend.config import Settings, get_settings


@dataclass(frozen=True)
class AllowlistedActionSpec:
    """Definition of a safe, predefined simulated remediation action."""

    action_name: str
    risk_level: str  # LOW, MEDIUM, HIGH
    description: str
    rollback_action: str


ALLOWLISTED_ACTIONS: Dict[str, AllowlistedActionSpec] = {
    "cleanup_simulated_temp_files": AllowlistedActionSpec(
        action_name="cleanup_simulated_temp_files",
        risk_level="LOW",
        description="Clean simulated temporary cache files in /var/tmp/sim-cache on storage-service.",
        rollback_action="restore_simulated_temp_metadata",
    ),
    "restart_simulated_service": AllowlistedActionSpec(
        action_name="restart_simulated_service",
        risk_level="MEDIUM",
        description="Restart simulated application service to clear runaway worker threads.",
        rollback_action="restore_previous_service_snapshot",
    ),
    "restore_simulated_service": AllowlistedActionSpec(
        action_name="restore_simulated_service",
        risk_level="HIGH",
        description="Restore simulated database connectivity (db-server) and restart payment-api.",
        rollback_action="restore_previous_service_snapshot",
    ),
}


class RiskEngine:
    """Evaluates proposed remediation actions against allowlist and safety policies."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def is_allowlisted(self, action_name: str) -> bool:
        """Verify that the proposed action exists in the predefined allowlist."""
        return action_name in ALLOWLISTED_ACTIONS

    def evaluate(self, action_name: str, target_service: str) -> Dict[str, object]:
        """Classify risk level and determine whether human approval is required."""
        if action_name not in ALLOWLISTED_ACTIONS:
            return {
                "allowed": False,
                "action_name": action_name,
                "target_service": target_service,
                "risk_level": "HIGH",
                "requires_approval": True,
                "auto_approved": False,
                "policy_reason": f"Action '{action_name}' is NOT on the approved remediation allowlist and is blocked.",
            }

        spec = ALLOWLISTED_ACTIONS[action_name]
        risk = spec.risk_level

        if risk == "HIGH":
            # HIGH RISK must ALWAYS require explicit human approval
            requires_approval = True
            reason = (
                f"HIGH risk action '{action_name}' targeting '{target_service}' "
                "always requires explicit human approval before execution."
            )
        elif risk == "MEDIUM":
            requires_approval = bool(self.settings.require_approval_medium_risk)
            reason = (
                f"MEDIUM risk action '{action_name}' targeting '{target_service}' requires approval per safety policy."
                if requires_approval
                else f"MEDIUM risk action '{action_name}' auto-permitted by configured policy."
            )
        else:
            requires_approval = not bool(self.settings.auto_approve_low_risk)
            reason = (
                f"LOW risk action '{action_name}' auto-approved under policy (auto_approve_low_risk=True)."
                if not requires_approval
                else f"LOW risk action '{action_name}' requires approval (auto_approve_low_risk=False)."
            )

        return {
            "allowed": True,
            "action_name": action_name,
            "target_service": target_service,
            "risk_level": risk,
            "requires_approval": requires_approval,
            "auto_approved": not requires_approval,
            "description": spec.description,
            "rollback_action": spec.rollback_action,
            "policy_reason": reason,
        }
