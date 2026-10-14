import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pages_bot as bot


class RewriteTests(unittest.TestCase):
    def test_exact_owner_urls_keep_path_query_and_fragment(self):
        before = 'https://BEACNpool.github.io/ABCDE/pool/?q=x#library https://github.com/BEACNpool/ABCDE/blob/main/a.md'
        after = bot.rewrite(before, 'BEACNpool', 'BEACNLabs')
        self.assertEqual(after, 'https://beacnlabs.github.io/ABCDE/pool/?q=x#library https://github.com/BEACNLabs/ABCDE/blob/main/a.md')

    def test_history_names_and_lookalike_hosts_are_untouched(self):
        text = 'BEACNpool https://beacnpool.org https://beacnpool.github.io.evil.test/x https://github.com/BEACNpool-other/x BEACNpool.jsonld'
        self.assertEqual(bot.rewrite(text, 'BEACNpool', 'BEACNLabs'), text)

    def test_profile_urls_without_trailing_slash(self):
        self.assertEqual(bot.rewrite('<a href="https://github.com/BEACNpool?tab=repositories">', 'BEACNpool', 'BEACNLabs'), '<a href="https://github.com/BEACNLabs?tab=repositories">')

    def test_raw_api_protocol_relative_and_idempotence(self):
        text = '//beacnpool.github.io/x https://raw.githubusercontent.com/BEACNpool/x/main/a https://api.github.com/repos/BEACNpool/x'
        result = bot.rewrite(text, 'BEACNpool', 'BEACNLabs')
        self.assertNotIn('BEACNpool', result)
        self.assertNotIn('beacnpool.github.io', result)
        self.assertEqual(bot.rewrite(result, 'BEACNpool', 'BEACNLabs'), result)

    def test_site_root_and_case_sensitive_project_path(self):
        self.assertEqual(bot.site_url('BEACNLabs', 'ABCDE'), 'https://beacnlabs.github.io/ABCDE/')
        self.assertEqual(bot.site_url('BEACNLabs', 'beacnlabs.github.io'), 'https://beacnlabs.github.io/')

    def test_inventory_paginates(self):
        with patch.object(bot, 'github', side_effect=[[{'name': str(i)} for i in range(100)], [{'name': 'last'}]]) as get:
            self.assertEqual(len(bot.repositories('BEACNLabs')), 101)
            self.assertIn('page=2', get.call_args.args[0])

    def test_http_success_is_not_a_safety_verdict(self):
        repo = {'name': 'example', 'full_name': 'BEACNLabs/example', 'homepage': None}
        with patch.object(bot, 'fetch', return_value=({'status': 200}, b'<a href="https://beacnpool.github.io/x/">x</a>')):
            report = bot.audit_site(repo, 'BEACNLabs', 'BEACNpool', [''])
        self.assertIn('not_assessed', report['browser_security'])
        self.assertEqual(len(report['pages'][0]['stale_links']), 1)

    def test_route_escape_rejected(self):
        for path in ['../other/', 'https://other.test/', '/other/']:
            with self.assertRaises(ValueError):
                bot.audit_site({'name':'x','full_name':'BEACNLabs/x'}, 'BEACNLabs', 'BEACNpool', [path])


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        bot.git(self.repo, 'config', 'user.name', 'Test')
        bot.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        self.before = b'<a href="https://beacnpool.github.io/ABCDE/">BEACNpool archive</a>\n'
        (self.repo / 'index.html').write_bytes(self.before)
        bot.git(self.repo, 'add', 'index.html')
        bot.git(self.repo, 'commit', '-qm', 'Fixture')
        self.plan_file = self.root / 'plan.json'
        self.args = argparse.Namespace(repo=str(self.repo), owner='BEACNLabs', previous_owner='BEACNpool', files=['index.html'], output=str(self.plan_file))

    def tearDown(self):
        self.temp.cleanup()

    def apply(self):
        bot.apply(argparse.Namespace(repo=str(self.repo), plan=str(self.plan_file), backup=str(self.root / 'backup')))

    def test_backup_and_only_reviewed_change(self):
        bot.plan(self.args)
        self.apply()
        import tarfile
        with tarfile.open(self.root / 'backup/before.tar.gz') as archive:
            self.assertEqual(archive.extractfile('index.html').read(), self.before)
        self.assertIn(b'https://beacnlabs.github.io/ABCDE/', (self.repo / 'index.html').read_bytes())
        self.assertIn(b'BEACNpool archive', (self.repo / 'index.html').read_bytes())

    def test_dirty_worktree_rejected_without_writing(self):
        bot.plan(self.args)
        (self.repo / 'index.html').write_text('concurrent work')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual((self.repo / 'index.html').read_text(), 'concurrent work')

    def test_changed_head_rejects_stale_plan(self):
        bot.plan(self.args)
        bot.git(self.repo, 'commit', '--allow-empty', '-qm', 'Concurrent commit')
        with self.assertRaises(ValueError): self.apply()

    def test_tampered_plan_rejected(self):
        bot.plan(self.args)
        document = json.loads(self.plan_file.read_text())
        document['changes'][0]['after_sha256'] = '0' * 64
        self.plan_file.write_text(json.dumps(document))
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual((self.repo / 'index.html').read_bytes(), self.before)

    def test_path_traversal_and_symlinks_rejected(self):
        outside = self.root / 'outside'
        outside.write_text('keep')
        (self.repo / 'alias').symlink_to(outside)
        for name in ['../outside', str(outside), 'alias', '.git/config']:
            with self.assertRaises(ValueError): bot.safe_path(self.repo, name)

    def test_backup_cannot_pollute_checkout(self):
        bot.plan(self.args)
        with self.assertRaises(ValueError):
            bot.apply(argparse.Namespace(repo=str(self.repo), plan=str(self.plan_file), backup=str(self.repo / 'backup')))


if __name__ == '__main__':
    unittest.main()
