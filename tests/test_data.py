import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.data import ROOT, build_database, validate_database


class DataChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.source = ROOT / 'data/demo.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_reopen_without_network(self):
        destination = self.folder / 'fresh.sqlite3'
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            self.assertEqual(build_database(self.source, destination), destination)
        seed = json.loads(self.source.read_text(encoding='utf-8'))
        expected = {'schema_version':1, **{name:len(seed[name]) for name in ('concepts','facts','knowledge')}}
        self.assertEqual(validate_database(destination), expected)
        connection = sqlite3.connect(destination)
        try:
            self.assertEqual(connection.execute("SELECT object FROM facts WHERE id='name'").fetchone()[0], 'Саша')
            self.assertEqual(connection.execute("SELECT topic FROM knowledge WHERE id='rainbow_cause'").fetchone()[0], 'rainbow')
        finally:
            connection.close()

    def test_workspace_creation_without_hardlink_permissions(self):
        with tempfile.TemporaryDirectory(prefix='data-check-', dir=ROOT) as directory:
            destination = Path(directory) / 'workspace.sqlite3'
            with patch('arena.data.os.link', side_effect=PermissionError('hardlinks unavailable')):
                if os.name == 'nt':
                    build_database(self.source, destination)
                else:
                    self.skipTest('Windows-specific rename publication')
            self.assertGreater(validate_database(destination)['concepts'], 0)

    def test_racing_destination_untouched(self):
        if os.name != 'nt':
            self.skipTest('Windows-specific rename collision')
        destination = self.folder / 'race.sqlite3'
        real_rename = os.rename

        def race(source, target):
            Path(target).write_bytes(b'racing writer data')
            return real_rename(source, target)

        with patch('arena.data.os.rename', side_effect=race):
            with self.assertRaises(ValueError):
                build_database(self.source, destination)
        self.assertEqual(destination.read_bytes(), b'racing writer data')

    def test_existing_file_untouched(self):
        destination = self.folder / 'custom.sqlite3'
        destination.write_bytes(b'user database bytes')
        with self.assertRaises(ValueError):
            build_database(self.source, destination)
        self.assertEqual(destination.read_bytes(), b'user database bytes')

    def test_bad_json_and_invalid_references(self):
        source = self.folder / 'bad.json'
        source.write_text('{bad', encoding='utf-8')
        destination = self.folder / 'bad.sqlite3'
        with self.assertRaises(ValueError):
            build_database(source, destination)
        self.assertFalse(destination.exists())
        data = json.loads(self.source.read_text(encoding='utf-8'))
        data['facts'][0]['object'] = 'missing-concept'
        source.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            build_database(source, destination)
        self.assertFalse(destination.exists())

    def test_missing_and_incompatible_database(self):
        missing = self.folder / 'missing.sqlite3'
        with self.assertRaises(ValueError):
            validate_database(missing)
        self.assertFalse(missing.exists())
        wrong = self.folder / 'wrong.sqlite3'
        wrong.write_bytes(b'not sqlite')
        with self.assertRaises(ValueError):
            validate_database(wrong)


if __name__ == '__main__':
    unittest.main()
