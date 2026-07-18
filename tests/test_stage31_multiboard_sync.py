from __future__ import annotations

import unittest

from scripts.stage31_multiboard_sync import _progress_sample


def result_for(*, mode: str = "time_spec", generation: int = 7) -> dict:
    return {
        "sync": {
            "active_generation": generation,
            "streaming": True,
            "first_time_seen": True,
            "first_spec_seen": True,
        },
        "snapshot": {
            "profile": {"mode": mode},
            "pipeline": {
                "stream_accepting": True,
                "cmac_mux_stale_science_frame": False,
            },
            "counters": {
                "time_packets": 100,
                "spec_packets": 200,
                "rfdc_dropped": 0,
            },
        },
    }


class Stage31ProgressTests(unittest.TestCase):
    def test_dual_stream_requires_both_first_packets_and_healthy_pipeline(self) -> None:
        result = result_for()
        healthy, sample = _progress_sample(result, generation=7)
        self.assertTrue(healthy)
        self.assertTrue(sample["need_time"])
        self.assertTrue(sample["need_spec"])

        result["sync"]["first_spec_seen"] = False
        self.assertFalse(_progress_sample(result, generation=7)[0])
        result["sync"]["first_spec_seen"] = True
        result["snapshot"]["pipeline"]["stream_accepting"] = False
        self.assertFalse(_progress_sample(result, generation=7)[0])

    def test_profile_only_requires_its_enabled_stream(self) -> None:
        result = result_for(mode="time_only")
        result["sync"]["first_spec_seen"] = False
        healthy, sample = _progress_sample(result, generation=7)
        self.assertTrue(healthy)
        self.assertTrue(sample["need_time"])
        self.assertFalse(sample["need_spec"])

    def test_generation_and_stale_cmac_frame_are_rejected(self) -> None:
        result = result_for()
        self.assertFalse(_progress_sample(result, generation=8)[0])
        result["snapshot"]["pipeline"]["cmac_mux_stale_science_frame"] = True
        self.assertFalse(_progress_sample(result, generation=7)[0])


if __name__ == "__main__":
    unittest.main()
