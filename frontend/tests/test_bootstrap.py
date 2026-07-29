from unittest.mock import patch

import bootstrap


def test_ensure_backend_running_is_noop_when_already_reachable():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        with patch("bootstrap.subprocess.Popen") as mock_popen:
            bootstrap.ensure_backend_running()

    assert not mock_popen.called


def test_ensure_backend_running_spawns_and_waits_when_not_reachable():
    with patch("bootstrap._backend_is_reachable", side_effect=[False, False, True]):
        with patch("bootstrap.subprocess.Popen") as mock_popen:
            with patch("bootstrap.time.sleep") as mock_sleep:
                bootstrap.ensure_backend_running()

    assert mock_popen.called
    assert mock_sleep.called
