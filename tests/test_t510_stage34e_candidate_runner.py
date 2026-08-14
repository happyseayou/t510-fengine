import unittest
from unittest import mock

from scripts import t510_stage34e_candidate_runner as runner


class Stage34eCandidateRunnerTests(unittest.TestCase):
    def test_candidate_configure_retries_transient_hardware_busy(self) -> None:
        with mock.patch.object(
            runner.fullband,
            "_http_json",
            side_effect=[RuntimeError("HARDWARE_BUSY"), {"streaming": False}],
        ) as request, mock.patch.object(runner.time, "sleep"):
            result = runner.agent_post_with_busy_retry(
                "http://board.invalid",
                "/api/v2/configure",
                {"bitstream_id": runner.CANDIDATE_ID},
                timeout=240.0,
            )
        self.assertFalse(result["streaming"])
        self.assertEqual(request.call_count, 2)

    def test_candidate_catalog_is_isolated_discovery_and_keeps_v34_out(self) -> None:
        value = runner.candidate_config("a" * 64)
        self.assertEqual(value["default_bitstream_id"], runner.CANDIDATE_ID)
        self.assertEqual(len(value["bitstreams"]), 1)
        candidate = value["bitstreams"][0]
        self.assertEqual(candidate["core_version"], runner.CANDIDATE_CORE)
        self.assertEqual(candidate["mts_adc_target_latency"], -1)
        self.assertEqual(candidate["mts_dac_target_latency"], -1)
        self.assertEqual(candidate["sha256"], "a" * 64)

    def test_remote_paths_are_fixed_and_not_release_tree(self) -> None:
        self.assertEqual(runner.REMOTE_ROOT, "/run/t510-stage34e-v36-agent")
        self.assertNotIn("/opt/t510-agent/current", runner.REMOTE_ROOT)
        self.assertEqual(runner.PRODUCTION_ID, "fengine-0x00010034")


if __name__ == "__main__":
    unittest.main()
