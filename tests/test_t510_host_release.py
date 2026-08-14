from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class T510HostReleaseTests(unittest.TestCase):
    def test_receiver_service_uses_current_cli_and_nic(self) -> None:
        service = (ROOT / "deploy/t510/t510-time-rx.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("--interface enp1s0f0np0", service)
        self.assertIn("--initial-sample-rate-msps 160", service)
        self.assertNotIn("--initial-" + "bandwidth-mhz", service)
        self.assertNotIn("--spec-" + "layout", service)

    def test_tuning_normalizes_legacy_raw_table_hooks(self) -> None:
        tune = (ROOT / "scripts/host_t510_rx_tune.sh").read_text(encoding="utf-8")
        self.assertIn("/^T510_STAGE[0-9][[:alnum:]_]*_RX$/", tune)
        self.assertIn(
            'iptables -t raw -D PREROUTING -j "${legacy_chain}"', tune
        )
        self.assertIn('iptables -t raw -X "${legacy_chain}"', tune)
        self.assertIn("iptables -t raw -I PREROUTING 1 -j T510_RX", tune)

    def test_release_installs_current_tuning_asset(self) -> None:
        publisher = (ROOT / "scripts/t510_publish_receiver.sh").read_text(
            encoding="utf-8"
        )
        installer = (ROOT / "deploy/t510/install-receiver.sh").read_text(
            encoding="utf-8"
        )
        unit = (ROOT / "deploy/t510/t510-rx-tune.service").read_text(
            encoding="utf-8"
        )
        self.assertIn('scripts/host_t510_rx_tune.sh"', publisher)
        self.assertIn('STAGE="${ROOT}/build/receiver/latest"', publisher)
        self.assertNotIn("RELEASE_ID", publisher)
        self.assertNotIn("/releases/${RELEASE_ID}", installer)
        self.assertIn('CURRENT="${INSTALL_ROOT}/current"', installer)
        self.assertIn('cp -aL "${SOURCE}" "${NEXT}"', installer)
        self.assertIn('rm -rf -- "${PREVIOUS}" "${RELEASES}"', installer)
        self.assertIn("/current/host_t510_rx_tune.sh", unit)
        self.assertIn("--queue-count 20 enp1s0f0np0", unit)

    def test_board_release_is_latest_only(self) -> None:
        publisher = (ROOT / "scripts/t510_publish_board.sh").read_text(
            encoding="utf-8"
        )
        installer = (ROOT / "deploy/t510/install-on-board.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('STAGE="${ROOT}/build/board/latest/package"', publisher)
        self.assertIn('OVERLAY_DIR="${T510_OVERLAY_DIR:-${ROOT}/overlay}"', publisher)
        self.assertNotIn("RELEASE_ID", publisher)
        self.assertNotIn("/releases/${RELEASE_ID}", installer)
        self.assertIn('CURRENT="${INSTALL_ROOT}/current"', installer)
        self.assertIn('cp -aL "${SOURCE}" "${NEXT}"', installer)
        self.assertIn("global_pl_state.json", installer)
        self.assertIn('state["bitfile_name"] = str(bit_path)', installer)
        self.assertIn('rm -rf -- "${PREVIOUS}" "${RELEASES}"', installer)

    def test_release_profiles_use_capture_nic_mac(self) -> None:
        for name in (
            "configure_160_time_only.example.json",
            "configure_320_time_only.example.json",
        ):
            profile = json.loads(
                (ROOT / "config/t510" / name).read_text(encoding="utf-8")
            )
            self.assertTrue(profile["endpoints"])
            self.assertEqual(
                {endpoint["destination_mac"] for endpoint in profile["endpoints"]},
                {"4c:bb:47:2b:42:6e"},
            )


if __name__ == "__main__":
    unittest.main()
