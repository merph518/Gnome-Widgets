"""Tests for conky-widgets-voices: the catalog listing, and a download that is kept only when
its size and checksum match the catalog's. No test reaches the network."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import support

BIN = os.path.join(os.path.dirname(support.SRC), 'bin', 'conky-widgets-voices')


def load():
    loader = importlib.machinery.SourceFileLoader('voices', BIN)
    spec = importlib.util.spec_from_loader('voices', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


voices = load()

MODEL, CONFIG = b'model' * 1000, b'{"audio": {}}'


def entry(quality='medium', speakers=1, model=MODEL, config=CONFIG):
    folder = 'en/en_GB/alan/' + quality + '/en_GB-alan-' + quality
    return {'quality': quality, 'num_speakers': speakers, 'files': {
        folder + '.onnx': {'size_bytes': len(model), 'md5_digest': hashlib.md5(model).hexdigest()},
        folder + '.onnx.json': {'size_bytes': len(config), 'md5_digest': hashlib.md5(config).hexdigest()},
        folder.rsplit('/', 1)[0] + '/MODEL_CARD': {'size_bytes': 1, 'md5_digest': ''}}}


class VoicesTest(support.TempDirTest):

    def setUp(self):
        super().setUp()
        self.piper = os.path.join(self.dir, 'piper')
        patcher = mock.patch.object(voices, 'PIPER_DIR', self.piper)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.served = {}                                # repository path -> bytes
        patcher = mock.patch.object(voices, 'get', side_effect=lambda path: support.response(self.served[path]))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.catalog = {'en_GB-alan-medium': entry(), 'en_GB-alan-low': entry('low'),
                        'de_DE-karlsson-low': entry('low')}

    def serve(self, name, model=MODEL, config=CONFIG):
        for path, _, _ in voices.model_files(self.catalog[name]):
            self.served[path] = model if path.endswith('.onnx') else config

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = voices.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_a_voice_is_its_model_and_its_config_without_the_model_card(self):
        paths = [os.path.basename(path) for path, _, _ in voices.model_files(self.catalog['en_GB-alan-low'])]
        self.assertEqual(sorted(paths), ['en_GB-alan-low.onnx', 'en_GB-alan-low.onnx.json'])

    def test_list_marks_the_installed_and_defaults_to_english(self):
        os.makedirs(self.piper)
        open(os.path.join(self.piper, 'en_GB-alan-low.onnx'), 'w').close()
        with mock.patch.object(voices, 'catalog', return_value=self.catalog):
            code, out, _ = self.run_main('list')
            _, german, _ = self.run_main('list', 'de_')
        rows = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual([r[0] for r in rows], ['*', ' '])
        self.assertEqual([r[2:].split()[0] for r in rows], ['en_GB-alan-low', 'en_GB-alan-medium'])
        self.assertNotIn('de_DE', out)
        self.assertIn('de_DE-karlsson-low', german)

    def test_add_downloads_both_files_into_the_piper_folder(self):
        self.serve('en_GB-alan-medium')
        with mock.patch.object(voices, 'catalog', return_value=self.catalog):
            code, _, _ = self.run_main('add', 'en_GB-alan-medium')
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(self.piper)), ['en_GB-alan-medium.onnx', 'en_GB-alan-medium.onnx.json'])
        with open(os.path.join(self.piper, 'en_GB-alan-medium.onnx'), 'rb') as f:
            self.assertEqual(f.read(), MODEL)

    def test_a_download_that_does_not_match_the_catalog_leaves_nothing(self):
        self.serve('en_GB-alan-medium', model=b'x' * len(MODEL))        # the right size, the wrong bytes
        with mock.patch.object(voices, 'catalog', return_value=self.catalog):
            with self.assertRaises(OSError):
                self.run_main('add', 'en_GB-alan-medium')
        self.assertFalse(os.path.exists(os.path.join(self.piper, 'en_GB-alan-medium.onnx')))
        self.assertFalse([f for f in os.listdir(self.piper) if f.endswith('.part')])

    def test_an_installed_voice_is_not_fetched_again(self):
        os.makedirs(self.piper)
        open(os.path.join(self.piper, 'en_GB-alan-low.onnx'), 'w').close()
        with mock.patch.object(voices, 'catalog', return_value=self.catalog):
            code, out, _ = self.run_main('add', 'en_GB-alan-low')
        self.assertEqual(code, 0)
        self.assertIn('already', out)
        voices.get.assert_not_called()

    def test_an_unknown_name_downloads_nothing(self):
        with mock.patch.object(voices, 'catalog', return_value=self.catalog):
            code, _, err = self.run_main('add', 'en_GB-alan-medium', 'en_GB-nobody-high')
        self.assertEqual(code, 2)
        self.assertIn('en_GB-nobody-high', err)
        voices.get.assert_not_called()
        self.assertFalse(os.path.exists(self.piper))

    def test_other_commands_print_the_usage(self):
        self.assertEqual(self.run_main()[0], 2)
        self.assertEqual(self.run_main('add')[0], 2)
        self.assertEqual(self.run_main('remove', 'x')[0], 2)
