"""The speech widget's parts read one speaking hook's state folder (support.SpeechFixture):
speechqueue.py for the widget, tray_model.py for the widget's own menu. They must agree on the
voice and volume, or the menu and the widget contradict each other."""
import unittest

import sys

import support

sys.path.insert(0, support.SRC)
speechqueue = support.load_speechqueue()
import tray_model  # noqa: E402

ME = '11111111-aaaa'


class SameStateTest(support.TempDirTest):
    def setUp(self):
        super().setUp()
        self.f = support.SpeechFixture(self.dir)
        self.redirect(tray_model, SPEAK='speak-attention')

    def read(self):
        state = speechqueue.read_state(self.f.speak, self.f.sessions, self.f.proc)
        return state, tray_model.speech_settings()

    def test_idle_with_the_defaults(self):
        state, settings = self.read()
        self.assertIsNone(state['now'])
        self.assertEqual((state['voice'], state['volume']), settings)

    def test_speaking_and_the_settings(self):
        self.f.session(300, ME, 'Claude Voice Widget')
        self.f.file(ME + '.replies')
        self.f.now(ME, 'Claude Voice Widget', 'Waiting on PR 110.')
        self.f.settings(voice='en_US-ryan-high', volume=0.5)
        state, settings = self.read()
        self.assertEqual(state['now']['session'], ME)
        self.assertEqual((state['voice'], state['volume']), settings, 'voice and volume')
        self.assertEqual([s['speech'] for s in state['sessions']], ['on'])

    def test_a_bad_settings_file_falls_back_alike(self):
        self.f.file('settings.json', '{"volume": "loud"')
        state, settings = self.read()
        self.assertEqual((state['voice'], state['volume']), settings)


if __name__ == '__main__':
    unittest.main()
