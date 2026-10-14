import json
import os
import unittest
from unittest.mock import patch, MagicMock

from taskctl.providers.multigravity import (
    DEFAULT_PROFILES,
    discover_profiles,
    _normalize_quota_item,
    get_profile_quotas,
    query_multigravity_route,
    route_target,
)
from taskctl.telemetry.sink import TelemetryEmitter


class TestMultigravityProvider(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_discover_profiles_from_taskctl_env(self):
        os.environ["TASKCTL_MULTIGRAVITY_PROFILES"] = "alice, bob, charlie "
        profiles = discover_profiles()
        self.assertEqual(profiles, ["alice", "bob", "charlie"])

    def test_discover_profiles_from_multigravity_env(self):
        os.environ.pop("TASKCTL_MULTIGRAVITY_PROFILES", None)
        os.environ["MULTIGRAVITY_PROFILES"] = "dev1, dev2"
        profiles = discover_profiles()
        self.assertEqual(profiles, ["dev1", "dev2"])

    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_discover_profiles_from_multigravity_list(self, mock_run, mock_which):
        os.environ.pop("TASKCTL_MULTIGRAVITY_PROFILES", None)
        os.environ.pop("MULTIGRAVITY_PROFILES", None)
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"name": "profile_alpha", "is_running": True},
                {"name": "profile_beta", "is_running": False},
            ]),
        )
        profiles = discover_profiles()
        self.assertEqual(profiles, ["profile_alpha", "profile_beta"])

    @patch("shutil.which", return_value=None)
    def test_discover_profiles_fallback(self, mock_which):
        os.environ.pop("TASKCTL_MULTIGRAVITY_PROFILES", None)
        os.environ.pop("MULTIGRAVITY_PROFILES", None)
        profiles = discover_profiles()
        self.assertEqual(profiles, DEFAULT_PROFILES)

    def test_normalize_quota_item_flat_schema(self):
        item = {
            "profile": "test_prof",
            "buckets": {
                "gemini": {"remaining_fraction": 0.85, "reset_time": "2026-10-20T00:00:00Z"},
            },
        }
        normalized = _normalize_quota_item(item)
        self.assertIn("gemini", normalized["buckets"])
        self.assertEqual(normalized["buckets"]["gemini"]["remaining_fraction"], 0.85)
        self.assertEqual(normalized["buckets"]["gemini"]["reset_time"], "2026-10-20T00:00:00Z")

    def test_normalize_quota_item_nested_groups_schema(self):
        item = {
            "profile": "luisfmb",
            "quota_known": True,
            "data": {
                "response": {
                    "groups": [
                        {
                            "displayName": "Gemini Models",
                            "buckets": [
                                {
                                    "bucketId": "gemini-weekly",
                                    "remainingFraction": 0.95,
                                    "resetTime": "2026-10-21T00:00:00Z",
                                },
                                {
                                    "bucketId": "gemini-5h",
                                    "remainingFraction": 0.70,
                                    "resetTime": "2026-10-14T18:00:00Z",
                                },
                            ],
                        },
                        {
                            "displayName": "Claude and GPT models",
                            "buckets": [
                                {
                                    "bucketId": "3p-weekly",
                                    "remainingFraction": 0.90,
                                    "resetTime": "2026-10-19T00:00:00Z",
                                },
                            ],
                        },
                    ],
                },
            },
        }
        normalized = _normalize_quota_item(item)
        self.assertIn("gemini", normalized["buckets"])
        # Should pick the most constrained fraction (0.70)
        self.assertEqual(normalized["buckets"]["gemini"]["remaining_fraction"], 0.70)
        self.assertEqual(normalized["buckets"]["gemini"]["reset_time"], "2026-10-14T18:00:00Z")
        self.assertIn("claude", normalized["buckets"])
        self.assertEqual(normalized["buckets"]["claude"]["remaining_fraction"], 0.90)

    def test_normalize_quota_item_unknown_quota(self):
        item = {
            "profile": "unopened_profile",
            "quota_known": False,
        }
        normalized = _normalize_quota_item(item)
        self.assertEqual(normalized["buckets"]["gemini"]["remaining_fraction"], 0.5)

    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_get_profile_quotas_dynamic(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"profile": "custom_agent_1", "buckets": {"gemini": {"remaining_fraction": 0.8}}},
                {"profile": "custom_agent_2", "buckets": {"gemini": {"remaining_fraction": 0.4}}},
            ]),
        )
        with patch.object(TelemetryEmitter, "record_provider_call") as mock_record:
            quotas = get_profile_quotas()
            self.assertIn("custom_agent_1", quotas)
            self.assertIn("custom_agent_2", quotas)
            self.assertTrue(mock_record.called)

    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_get_profile_quotas_with_filter(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"profile": "p1", "buckets": {"gemini": {"remaining_fraction": 0.8}}},
                {"profile": "p2", "buckets": {"gemini": {"remaining_fraction": 0.4}}},
            ]),
        )
        quotas = get_profile_quotas(profiles=["p1"])
        self.assertIn("p1", quotas)
        self.assertNotIn("p2", quotas)

    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_query_multigravity_route_success(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "profile": "agent_x",
                "model": "gemini-3.8-flash-low",
                "reason": "Dynamic router optimal pick",
            }),
        )
        with patch.object(TelemetryEmitter, "record_provider_call") as mock_record:
            route = query_multigravity_route(weight="light")
            self.assertIsNotNone(route)
            profile, model, reason = route
            self.assertEqual(profile, "agent_x")
            self.assertEqual(model, "gemini-3.8-flash-low")
            self.assertEqual(reason, "Dynamic router optimal pick")
            self.assertTrue(mock_record.called)

    @patch("shutil.which", return_value="/bin/multigravity")
    @patch("subprocess.run")
    def test_query_multigravity_route_failure(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Error: profile 'route' does not exist.",
        )
        route = query_multigravity_route(weight="medium")
        self.assertIsNone(route)

    @patch("taskctl.providers.multigravity.query_multigravity_route")
    @patch("taskctl.providers.multigravity.discover_profiles", return_value=["prof_a", "prof_b"])
    @patch("taskctl.providers.multigravity.get_profile_quotas")
    def test_route_target_local_dynamic(self, mock_quotas, mock_discover, mock_ext_route):
        mock_ext_route.return_value = None
        mock_quotas.return_value = {
            "prof_a": {"buckets": {"gemini": {"remaining_fraction": 0.3, "reset_time": "reset_a"}}},
            "prof_b": {"buckets": {"gemini": {"remaining_fraction": 0.9, "reset_time": "reset_b"}}},
        }

        # Medium weight picks prof_b and gemini-3.8-flash-medium
        best_p, best_m, reason = route_target(weight="medium")
        self.assertEqual(best_p, "prof_b")
        self.assertEqual(best_m, "gemini-3.8-flash-medium")
        self.assertIn("90.0%", reason)

        # Light weight picks gemini-3.8-flash-low
        best_p, best_m, reason = route_target(weight="light")
        self.assertEqual(best_p, "prof_b")
        self.assertEqual(best_m, "gemini-3.8-flash-low")

    @patch("taskctl.providers.multigravity.query_multigravity_route")
    @patch("taskctl.providers.multigravity.discover_profiles", return_value=["prof_empty"])
    @patch("taskctl.providers.multigravity.get_profile_quotas")
    def test_route_target_depleted_fallback(self, mock_quotas, mock_discover, mock_ext_route):
        mock_ext_route.return_value = None
        mock_quotas.return_value = {
            "prof_empty": {"buckets": {"gemini": {"remaining_fraction": 0.005, "reset_time": "reset_empty"}}},
        }
        best_p, best_m, reason = route_target(weight="medium")
        self.assertEqual(best_p, "prof_empty")
        self.assertEqual(best_m, "claude-opus-4-6-thinking")
        self.assertIn("depleted", reason)

    @patch("taskctl.providers.multigravity.query_multigravity_route")
    def test_route_target_prefers_external_route(self, mock_ext_route):
        mock_ext_route.return_value = ("router_profile", "router_model", "router_reason")
        best_p, best_m, reason = route_target(weight="medium")
        self.assertEqual(best_p, "router_profile")
        self.assertEqual(best_m, "router_model")
        self.assertEqual(reason, "router_reason")


if __name__ == "__main__":
    unittest.main()
