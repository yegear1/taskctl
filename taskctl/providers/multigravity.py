"""Multigravity quota routing and profile isolation provider.

Designed to interface with the external multigravity-cli project:
https://github.com/yegear1/multigravity-cli
"""

import json
import os
import shutil
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple

from taskctl.telemetry.sink import get_telemetry_emitter

DEFAULT_PROFILES: List[str] = ["yegear", "luisfmb", "joaoww"]
MULTIGRAVITY_PROFILES: List[str] = DEFAULT_PROFILES

__all__ = [
    "DEFAULT_PROFILES",
    "MULTIGRAVITY_PROFILES",
    "discover_profiles",
    "get_profile_quotas",
    "query_multigravity_route",
    "route_target",
]


def discover_profiles() -> List[str]:
    """Discover available Multigravity profiles dynamically.

    Priority:
    1. Environment variables TASKCTL_MULTIGRAVITY_PROFILES or MULTIGRAVITY_PROFILES (comma-separated).
    2. Dynamic inspection via `multigravity list --json`.
    3. Fallback to DEFAULT_PROFILES.
    """
    env_profiles = os.environ.get("TASKCTL_MULTIGRAVITY_PROFILES") or os.environ.get("MULTIGRAVITY_PROFILES")
    if env_profiles:
        parsed = [p.strip() for p in env_profiles.split(",") if p.strip()]
        if parsed:
            return parsed

    if shutil.which("multigravity"):
        try:
            res = subprocess.run(
                ["multigravity", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                if isinstance(data, list):
                    discovered: List[str] = []
                    for item in data:
                        name = item.get("name") or item.get("profile")
                        if name and name not in discovered:
                            discovered.append(str(name))
                    if discovered:
                        return discovered
        except Exception:
            pass

    return list(DEFAULT_PROFILES)


def _normalize_quota_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes various quota payload formats into standard buckets.

    Ensures item['buckets']['gemini'] and item['buckets']['claude'] exist
    with 'remaining_fraction' (float) and 'reset_time' (str).
    """
    normalized = dict(item)
    buckets = dict(normalized.get("buckets", {}))

    if "gemini" in buckets and isinstance(buckets["gemini"], dict):
        g = buckets["gemini"]
        buckets["gemini"] = {
            "remaining_fraction": float(g.get("remaining_fraction", g.get("remainingFraction", 0.0))),
            "reset_time": str(g.get("reset_time", g.get("resetTime", "N/A"))),
        }
    else:
        groups = (
            normalized.get("data", {})
            .get("response", {})
            .get("groups", [])
        )
        gemini_fractions: List[float] = []
        gemini_resets: List[str] = []
        claude_fractions: List[float] = []
        claude_resets: List[str] = []

        if isinstance(groups, list):
            for group in groups:
                group_name = str(group.get("displayName", "")).lower()
                group_buckets = group.get("buckets", [])
                if isinstance(group_buckets, list):
                    for b in group_buckets:
                        b_id = str(b.get("bucketId", "")).lower()
                        rem = float(b.get("remainingFraction", b.get("remaining_fraction", 0.0)))
                        rst = str(b.get("resetTime", b.get("reset_time", "N/A")))
                        if "gemini" in group_name or "gemini" in b_id:
                            gemini_fractions.append(rem)
                            gemini_resets.append(rst)
                        elif "claude" in group_name or "gpt" in group_name or "3p" in b_id:
                            claude_fractions.append(rem)
                            claude_resets.append(rst)

        if gemini_fractions:
            min_idx = gemini_fractions.index(min(gemini_fractions))
            buckets["gemini"] = {
                "remaining_fraction": gemini_fractions[min_idx],
                "reset_time": gemini_resets[min_idx],
            }
        else:
            buckets["gemini"] = {
                "remaining_fraction": 0.0,
                "reset_time": "N/A",
            }

        if claude_fractions:
            min_idx = claude_fractions.index(min(claude_fractions))
            buckets["claude"] = {
                "remaining_fraction": claude_fractions[min_idx],
                "reset_time": claude_resets[min_idx],
            }
        else:
            buckets["claude"] = {
                "remaining_fraction": 0.0,
                "reset_time": "N/A",
            }

    normalized["buckets"] = buckets
    return normalized


def get_profile_quotas(profiles: Optional[List[str]] = None) -> Dict[str, Any]:
    """Retrieve and normalize AI token quotas across all discovered profiles.

    Args:
        profiles: Optional list of profile names to filter. If None, queries all profiles.
    """
    if not shutil.which("multigravity"):
        return {}
    start_time = time.perf_counter()
    success = False
    result: Dict[str, Any] = {}
    try:
        res = subprocess.run(
            ["multigravity", "quota", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    p_name = item.get("profile") or item.get("name")
                    if not p_name:
                        continue
                    p_name_str = str(p_name)
                    if profiles is not None and p_name_str not in profiles:
                        continue
                    result[p_name_str] = _normalize_quota_item(item)
            success = True
            return result
    except Exception:
        pass
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        get_telemetry_emitter().record_provider_call(
            provider="multigravity",
            operation="quota",
            duration_ms=duration_ms,
            success=success,
            metadata={"profiles_found": len(result)},
        )
    return {}


def query_multigravity_route(weight: str = "medium") -> Optional[Tuple[str, str, str]]:
    """Attempt dynamic routing directly via the multigravity route command.

    Returns:
        (profile, model, reason) if supported and successful, else None.
    """
    if not shutil.which("multigravity"):
        return None
    start_time = time.perf_counter()
    success = False
    try:
        res = subprocess.run(
            ["multigravity", "route", "--weight", weight, "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                p = data.get("profile")
                m = data.get("model")
                r = data.get("reason", "External route decision")
                if p and m:
                    success = True
                    return str(p), str(m), str(r)
    except Exception:
        pass
    finally:
        if success:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            get_telemetry_emitter().record_provider_call(
                provider="multigravity",
                operation="route",
                duration_ms=duration_ms,
                success=True,
                metadata={"weight": weight},
            )
    return None


def route_target(weight: str = "medium", profiles: Optional[List[str]] = None) -> Tuple[str, str, str]:
    """Calculate the optimal profile and model target based on dynamic quota telemetry.

    First attempts dynamic routing via `multigravity route`. If unavailable or unsupported,
    dynamically discovers active profiles and selects the target with the healthiest quota.
    """
    ext_route = query_multigravity_route(weight=weight)
    if ext_route is not None:
        return ext_route

    target_profiles = profiles if profiles is not None else discover_profiles()
    if not target_profiles:
        target_profiles = list(DEFAULT_PROFILES)

    quotas = get_profile_quotas(profiles=target_profiles)
    valid_profiles: List[Tuple[str, float, str]] = []

    for p in target_profiles:
        q = quotas.get(p)
        if q:
            gemini_bucket = q.get("buckets", {}).get("gemini", {})
            rem_frac = gemini_bucket.get("remaining_fraction", 0.0)
            reset_str = gemini_bucket.get("reset_time", "N/A")
            valid_profiles.append((p, rem_frac, reset_str))
        else:
            valid_profiles.append((p, 0.0, "N/A"))

    if not valid_profiles:
        valid_profiles = [("default", 0.0, "N/A")]

    valid_profiles.sort(key=lambda x: x[1], reverse=True)
    best_profile, best_fraction, best_reset = valid_profiles[0]

    if best_fraction >= 0.01:
        if weight == "light":
            model = "gemini-3.8-flash-low"
        else:
            model = "gemini-3.8-flash-medium"
        reason = f"Quota remaining: {best_fraction*100:.1f}% (Reset: {best_reset})"
        return best_profile, model, reason
    else:
        model = "claude-opus-4-6-thinking"
        reason = f"All Gemini buckets depleted (<1%). Using fallback with profile {best_profile}."
        return best_profile, model, reason
