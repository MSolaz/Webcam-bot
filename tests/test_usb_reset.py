import pytest

# usb_reset usa fcntl, que solo existe en Linux
pytest.importorskip("fcntl")

from webcam_bot.usb_reset import USBResetError, _walk_up_for_usb_device  # noqa: E402


def test_finds_usb_device_above_interface(tmp_path):
    device = tmp_path / "usb1" / "1-2"
    interface = device / "1-2:1.0"
    interface.mkdir(parents=True)
    (device / "busnum").write_text("1\n")
    (device / "devnum").write_text("7\n")

    assert _walk_up_for_usb_device(str(interface)) == "/dev/bus/usb/001/007"


def test_raises_if_no_usb_device(tmp_path):
    with pytest.raises(USBResetError):
        _walk_up_for_usb_device(str(tmp_path), max_levels=2)
