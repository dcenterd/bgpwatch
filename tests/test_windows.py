"""Windows support: paths, sound, notifications, console - run on any OS by passing `win=True`."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch import osutil, sound  # noqa: E402
from bgpwatch.alerts import Alerter  # noqa: E402
from bgpwatch.models import PathEvent  # noqa: E402


class PathTests(unittest.TestCase):
    def test_windows_folders_use_localappdata(self):
        env = {"LOCALAPPDATA": r"C:\Users\Zareh\AppData\Local"}
        self.assertEqual(osutil.state_dir(True, env), Path(env["LOCALAPPDATA"]) / "bgpwatch")
        self.assertEqual(osutil.cache_dir(True, env), Path(env["LOCALAPPDATA"]) / "bgpwatch" / "cache")

    def test_windows_without_localappdata_falls_back_to_the_profile(self):
        p = osutil.state_dir(True, {})
        self.assertEqual(p.parts[-3:], ("AppData", "Local", "bgpwatch"))

    def test_linux_folders_follow_xdg(self):
        self.assertEqual(osutil.state_dir(False, {"XDG_STATE_HOME": "/s"}), Path("/s/bgpwatch"))
        self.assertEqual(osutil.cache_dir(False, {"XDG_CACHE_HOME": "/c"}), Path("/c/bgpwatch"))
        self.assertEqual(osutil.state_dir(False, {}), Path.home() / ".local" / "state" / "bgpwatch")
        self.assertEqual(osutil.cache_dir(False, {}), Path.home() / ".cache" / "bgpwatch")

    def test_venv_interpreter_path(self):
        root = Path("proj")
        self.assertEqual(osutil.venv_python(root, True), root / ".venv" / "Scripts" / "python.exe")
        self.assertEqual(osutil.venv_python(root, False), root / ".venv" / "bin" / "python")

    def test_fixed_width_font(self):
        self.assertEqual(osutil.mono_font(True), "Consolas")
        self.assertEqual(osutil.mono_font(False), "monospace")


class ConsoleTests(unittest.TestCase):
    def test_no_console_gets_a_null_stream(self):         # a windowed .exe has sys.stdout = None
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            osutil.prepare_console()
            print("✔ ✖ →")                                  # must not raise
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)

    def test_cp1252_console_can_print_symbols(self):
        raw = io.BytesIO()
        fake = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(sys, "stdout", fake), mock.patch.object(sys, "stderr", io.StringIO()):
            osutil.prepare_console()
            print("RPKI ✔ valid ✖ → ⛔")
            sys.stdout.flush()
        self.assertIn("RPKI", raw.getvalue().decode("utf-8"))


class SoundTests(unittest.TestCase):
    def test_windows_plays_the_wav_through_winsound(self):
        fake = mock.MagicMock(SND_FILENAME=2, SND_ASYNC=1)
        with mock.patch.object(osutil, "IS_WINDOWS", True), mock.patch.dict(sys.modules, {"winsound": fake}):
            self.assertTrue(sound.play_alert())
        fake.PlaySound.assert_called_once()
        path, flags = fake.PlaySound.call_args.args
        self.assertTrue(path.endswith(".wav"))
        self.assertEqual(flags, 3)                          # file | async: never blocks the GUI

    def test_missing_winsound_means_tk_bell_fallback(self):
        with mock.patch.object(osutil, "IS_WINDOWS", True), mock.patch.dict(sys.modules, {"winsound": None}):
            self.assertFalse(sound.play_alert())


class NotifyTests(unittest.TestCase):
    def alerter(self):
        a = Alerter(Path(tempfile.mkdtemp()), notify=True, color=False)
        a.notify_cmd = None                                 # no notify-send, like on Windows
        return a

    def ev(self):
        return PathEvent("BEST_CHANGED", "8.8.8.8", "8.8.8.0/24", "consensus", (1, 2), (1, 3))

    def test_without_any_mechanism_nothing_can_notify(self):
        self.assertFalse(self.alerter().can_notify)

    def test_tray_balloon_is_used_when_set(self):
        a, calls = self.alerter(), []
        a.notifier = lambda title, body: calls.append((title, body))
        self.assertTrue(a.can_notify)
        a.handle(self.ev())
        self.assertEqual(len(calls), 1)
        self.assertIn("8.8.8.8", calls[0][0])

    def test_switch_off_and_failures_are_safe(self):
        a, calls = self.alerter(), []
        a.notifier = lambda t, b: calls.append(t)
        a.notify_enabled = False
        a.handle(self.ev())
        self.assertEqual(calls, [])
        a.notify_enabled = True
        a.notifier = mock.Mock(side_effect=RuntimeError("tray gone"))
        a.handle(self.ev())                                 # must not raise

    def test_tray_notify_forwards_to_pystray(self):
        from bgpwatch.tray import Tray
        t = Tray(mock.Mock())
        t.icon = mock.Mock()
        t.notify("Title", "Body")
        t.icon.notify.assert_called_once_with("Body", "Title")
        t.icon = None
        t.notify("x", "y")                                  # no icon: harmless


if __name__ == "__main__":
    unittest.main()
