from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionProfile(str, Enum):
    READ_ONLY = "read_only"
    ASSIST_ONLY = "assist_only"
    EXECUTE_SAFE = "execute_safe"
    EXECUTE_WITH_CONFIRMATION = "execute_with_confirmation"
    FULL_TRUSTED = "full_trusted"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str


class PolicyEngine:
    """Runtime policy evaluator for tool actions based on permission profile and risk."""

    _ORDER = {
        PermissionProfile.READ_ONLY: 0,
        PermissionProfile.ASSIST_ONLY: 1,
        PermissionProfile.EXECUTE_SAFE: 2,
        PermissionProfile.EXECUTE_WITH_CONFIRMATION: 3,
        PermissionProfile.FULL_TRUSTED: 4,
    }

    def __init__(self, profile: PermissionProfile = PermissionProfile.EXECUTE_SAFE) -> None:
        self._profile = profile

    @property
    def profile(self) -> PermissionProfile:
        return self._profile

    def set_profile(self, profile: PermissionProfile) -> None:
        self._profile = profile

    def evaluate_tool_risk(self, risk_level: str, safe_mode: bool) -> RiskDecision:
        risk = RiskLevel(risk_level)
        profile = self._profile

        if profile == PermissionProfile.READ_ONLY:
            return RiskDecision(False, False, "read_only_profile_blocks_tool_execution")
        if profile == PermissionProfile.ASSIST_ONLY:
            if risk == RiskLevel.LOW:
                return RiskDecision(True, False, "assist_only_allows_low_risk")
            return RiskDecision(False, False, "assist_only_blocks_non_low_risk")

        if profile == PermissionProfile.EXECUTE_SAFE:
            if risk == RiskLevel.LOW:
                return RiskDecision(True, False, "execute_safe_allows_low")
            if risk == RiskLevel.MEDIUM:
                return RiskDecision(True, True, "execute_safe_requires_confirmation_for_medium")
            return RiskDecision(False, False, "execute_safe_blocks_high_critical")

        if profile == PermissionProfile.EXECUTE_WITH_CONFIRMATION:
            if risk == RiskLevel.CRITICAL and safe_mode:
                return RiskDecision(False, False, "safe_mode_blocks_critical")
            if risk in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}:
                return RiskDecision(True, True, "confirmation_required")
            return RiskDecision(True, False, "low_allowed")

        # full_trusted
        if safe_mode and risk == RiskLevel.CRITICAL:
            return RiskDecision(False, False, "safe_mode_blocks_critical")
        return RiskDecision(True, False, "full_trusted")

    def can_mutate_admin_state(self) -> bool:
        return self._ORDER[self._profile] >= self._ORDER[PermissionProfile.EXECUTE_WITH_CONFIRMATION]
