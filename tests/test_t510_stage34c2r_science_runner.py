from __future__ import annotations
import sys
from pathlib import Path

import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-34'))
import t510_adc_correlated_noise_campaign as c34c
import t510_stage34c2r_science_runner as runner


class Stage34c2rScienceRunnerTest(unittest.TestCase):
    def test_candidate_catalog_is_isolated_discovery_only_v35(self) -> None:
        config = runner.candidate_config({})
        self.assertEqual(config["default_bitstream_id"], runner.CANDIDATE_ID)
        self.assertEqual(len(config["bitstreams"]), 1)
        bitstream = config["bitstreams"][0]
        self.assertEqual(bitstream["core_version"], runner.CANDIDATE_CORE)
        self.assertEqual(bitstream["sha256"], runner.CANDIDATE_SHA256)
        self.assertEqual(bitstream["mts_adc_target_latency"], -1)
        self.assertEqual(bitstream["mts_dac_target_latency"], -1)

    def test_shared_configure_builder_can_select_candidate_without_changing_default(self) -> None:
        template = {
            "endpoints": [
                {"stream": "TIME", "enabled": True},
                {"stream": "SPEC", "enabled": False},
            ]
        }
        production = c34c.configure_body(template, 160, "spec_only", 1020.0)
        candidate = c34c.configure_body(
            template,
            320,
            "spec_only",
            1020.0,
            bitstream_id=runner.CANDIDATE_ID,
        )
        self.assertEqual(production["bitstream_id"], runner.PRODUCTION_ID)
        self.assertEqual(candidate["bitstream_id"], runner.CANDIDATE_ID)
        self.assertEqual(candidate["profile"]["sample_rate_msps"], 320)

    @mock.patch.object(runner, "remote", return_value="ok")
    def test_remote_sudo_wraps_the_entire_compound_command(self, call: mock.Mock) -> None:
        runner.remote_sudo("xilinx@board", "rm -rf -- /run/example && install -d /run/example")
        command = call.call_args.args[1]
        self.assertIn("sudo -S sh -c", command)
        self.assertIn("rm -rf -- /run/example && install -d /run/example", command)


if __name__ == "__main__":
    unittest.main()
