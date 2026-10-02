"""Multigravity quota routing and profile isolation provider.

Designed to interface with the external multigravity-cli project:
https://github.com/yegear1/multigravity-cli
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

MULTIGRAVITY_PROFILES = ["yegear", "luisfmb", "joaoww"]

def get_profile_quotas() -> Dict[str, Any]:
    if not shutil.which("multigravity"):
        return {}
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
            profiles: Dict[str, Any] = {}
            for item in data:
                p_name = item.get("profile")
                if p_name in MULTIGRAVITY_PROFILES:
                    profiles[p_name] = item
            return profiles
    except Exception:
        pass
    return {}

def route_target(weight: str = "medium") -> Tuple[str, str, str]:
    quotas = get_profile_quotas()
    valid_profiles: List[Tuple[str, float, str]] = []

    for p in MULTIGRAVITY_PROFILES:
        q = quotas.get(p)
        if q:
            gemini_bucket = q.get("buckets", {}).get("gemini", {})
            rem_frac = gemini_bucket.get("remaining_fraction", 0.0)
            reset_str = gemini_bucket.get("reset_time", "N/A")
            valid_profiles.append((p, rem_frac, reset_str))
        else:
            valid_profiles.append((p, 0.5, "N/A"))

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
