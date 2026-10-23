import sys
import wave
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch import sound  # noqa: E402


def make_app(muted=False, muted_targets=()):
    """Minimal stand-in for BGPWatchApp with just what _beep needs; root.after is recorded."""
    from bgpwatch.gui import BGPWatchApp
    app = SimpleNamespace(v_mute=SimpleNamespace(get=lambda: muted), root=mock.Mock(),
                          muted_targets=set(muted_targets), ALERT_REPEATS=BGPWatchApp.ALERT_REPEATS,
                          ALERT_SPAN_S=BGPWatchApp.ALERT_SPAN_S)
    app._beep_burst = lambda t="": BGPWatchApp._beep_burst(app, t)
    return app


def count_beeps(path):
    with wave.open(str(path)) as w:
        data = w.readframes(w.getnframes())
        rate = w.getframerate()
    win = int(rate * 0.01)
    beeps, active = 0, False
    for i in range(0, len(data) // 2 - win, win):
        loud = max(abs(int.from_bytes(data[2 * j:2 * j + 2], "little", signed=True))
                   for j in range(i, i + win)) > 1000
        if loud and not active:
            beeps += 1
        active = loud
    return beeps


class SoundTests(unittest.TestCase):
    def test_wav_has_three_beeps(self):
        self.assertEqual(count_beeps(sound._make_wav()), 3)

    def test_alert_is_three_bursts_over_ten_seconds(self):
        from bgpwatch.gui import BGPWatchApp
        app = make_app()
        with mock.patch("bgpwatch.gui.play_alert", return_value=True) as play:
            BGPWatchApp._beep(app)
            self.assertEqual(play.call_count, 1)                      # first burst right away
            delays = [c.args[0] for c in app.root.after.call_args_list]
            self.assertEqual(delays, [5000, 10000])                   # then at 5 s and 10 s
            for c in app.root.after.call_args_list:                   # let the timers fire
                c.args[1]()
            self.assertEqual(play.call_count, 3)                      # 3 bursts x 3 beeps

    def test_muting_stops_the_remaining_bursts(self):
        from bgpwatch.gui import BGPWatchApp
        app = make_app()
        muted = {"on": False}
        app.v_mute = SimpleNamespace(get=lambda: muted["on"])
        with mock.patch("bgpwatch.gui.play_alert", return_value=True) as play:
            BGPWatchApp._beep(app)
            muted["on"] = True                                        # user mutes after burst 1
            for c in app.root.after.call_args_list:
                c.args[1]()
            self.assertEqual(play.call_count, 1)

    def test_beep_plays_unless_muted(self):
        from bgpwatch.gui import BGPWatchApp
        for muted, expected in ((False, 1), (True, 0)):
            app = make_app(muted)
            with mock.patch("bgpwatch.gui.play_alert", return_value=True) as play:
                BGPWatchApp._beep(app)
            self.assertEqual(play.call_count, expected, f"muted={muted}")

    def test_per_target_mute(self):
        from bgpwatch.gui import BGPWatchApp
        app = make_app(muted_targets={"8.8.8.8"})
        with mock.patch("bgpwatch.gui.play_alert", return_value=True) as play:
            BGPWatchApp._beep(app, "8.8.8.8")
            self.assertEqual(play.call_count, 0)
            BGPWatchApp._beep(app, "1.1.1.1")
            self.assertEqual(play.call_count, 1)

    def test_falls_back_to_tk_bell_three_times_per_burst(self):
        from bgpwatch.gui import BGPWatchApp
        app = make_app()
        with mock.patch("bgpwatch.gui.play_alert", return_value=False):
            BGPWatchApp._beep_burst(app)
        self.assertEqual(app.root.after.call_count, 3)


if __name__ == "__main__":
    unittest.main()
