import argparse
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pymacauto.cli import main
from test_core import MemoryAX

class CLITests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with patch('pymacauto.native.NativeBackend', return_value=MemoryAX()), redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_mutation_requires_explicit_execute(self):
        code, result = self.invoke(['click', '--pid', '42', '--identifier', 'apply'])
        self.assertNotEqual(code, 0)
        self.assertEqual(result['error'], 'UnsafeOperation')

    def test_click_reports_dispatch_not_verification(self):
        code, result = self.invoke(['click', '--pid', '42', '--identifier', 'apply', '--execute'])
        self.assertEqual(code, 0)
        self.assertFalse(result['result']['verified'])

    def test_find_is_read_only_json(self):
        code, result = self.invoke(['find', '--pid', '42', '--identifier', 'apply'])
        self.assertEqual(code, 0)
        self.assertEqual(result['result']['identifier'], 'apply')

    def test_help_selector_does_not_conflict_with_cli_help(self):
        from pymacauto.cli import parser
        args = parser().parse_args(['find', '--pid', '42', '--ax-help', 'hint'])
        self.assertEqual(args.help, 'hint')

    def test_ambiguous_cli_is_structured_failure(self):
        code, result = self.invoke(['find', '--pid', '42', '--title', 'Apply'])
        self.assertNotEqual(code, 0)
        self.assertEqual(result['error'], 'AmbiguousMatch')
