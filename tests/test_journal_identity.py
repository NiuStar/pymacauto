"""Filesystem/SQLite regression tests, supplemental to native Mac acceptance."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pymacauto.errors import UnsafeOperation
from pymacauto.journal import Journal, audit_journal


class JournalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve only the owned fixture root (/var -> /private/var on macOS).
        self.root=Path(self.temp.name).resolve()
        self.path=self.root/'ops.db'

    def journal(self,path=None):
        journal=Journal(path or self.path)
        self.addCleanup(journal.close)
        return journal

    def seed(self):
        j=self.journal();fp=j.fingerprint({'AXValue':'private-value'})
        j.claim('private-operation-id',fp);j.intent('private-operation-id')
        j.finish('private-operation-id',{'operation_id':'private-operation-id','status':'CONFIRMED',
                 'dispatch_attempted':True,'verified':True,'attempts':1,'AXValue':'private-value'})
        j.close()
        return fp

    def snapshot(self):
        return {p.name:(p.stat().st_mode,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest())
                for p in self.root.iterdir() if p.is_file()}

    def test_existing_empty_file_never_initialized(self):
        self.path.touch(mode=0o600)
        with self.assertRaises(UnsafeOperation):Journal(self.path)
        self.assertEqual(self.path.read_bytes(),b'')

    def test_missing_schema_never_reinitialized(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as db:
            with db:db.execute('DROP TABLE operations')
        before=self.path.read_bytes()
        with self.assertRaises(UnsafeOperation):Journal(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_symlink_ancestor_rejected(self):
        real=self.root/'real';real.mkdir(mode=0o700)
        link=self.root/'alias';link.symlink_to(real,target_is_directory=True)
        with self.assertRaises((OSError,UnsafeOperation)):Journal(link/'ops.db')
        self.assertEqual(list(real.iterdir()),[])

    def test_symlink_file_and_lock_rejected(self):
        target=self.root/'target';target.write_text('untouched');target.chmod(0o600)
        for suffix in ('','.lock'):
            with self.subTest(suffix=suffix):
                path=self.root/('symlink-'+str(len(suffix)))
                link=Path(str(path)+suffix);link.symlink_to(target)
                try:
                    with self.assertRaises((OSError,UnsafeOperation)):Journal(path)
                    self.assertEqual(target.read_text(),'untouched')
                finally:link.unlink()  # owned fixture only

    def test_aux_symlinks_rejected_before_connection(self):
        self.seed()
        target=self.root/'target';target.write_text('untouched');target.chmod(0o600)
        for suffix in ('-journal','-wal','-shm'):
            with self.subTest(suffix=suffix):
                link=Path(str(self.path)+suffix);link.symlink_to(target)
                try:
                    with patch('pymacauto.journal.sqlite3.connect') as connect:
                        with self.assertRaises(UnsafeOperation):Journal(self.path)
                        connect.assert_not_called()
                finally:link.unlink()
        self.assertEqual(target.read_text(),'untouched')

    def test_file_replacement_before_sqlite_open_detected(self):
        self.seed();connect=sqlite3.connect
        def replace(*args,**kwargs):
            self.path.rename(self.root/'original')
            self.path.touch(mode=0o600)
            return connect(*args,**kwargs)
        with patch('pymacauto.journal.sqlite3.connect',side_effect=replace):
            with self.assertRaises(UnsafeOperation):Journal(self.path)
        self.assertEqual(self.path.read_bytes(),b'')

    def test_parent_replacement_before_sqlite_open_detected(self):
        folder=self.root/'private';folder.mkdir(mode=0o700)
        path=folder/'ops.db';self.journal(path).close();connect=sqlite3.connect
        def replace(*args,**kwargs):
            folder.rename(self.root/'original');folder.mkdir(mode=0o700)
            return connect(*args,**kwargs)
        with patch('pymacauto.journal.sqlite3.connect',side_effect=replace):
            with self.assertRaises((OSError,UnsafeOperation,sqlite3.Error)):Journal(path)
        self.assertFalse(path.exists())  # mode=rw must not create replacement

    def test_boundaries_refuse_file_replacement(self):
        for method in ('fingerprint','lookup','claim','intent','finish'):
            with self.subTest(method=method),tempfile.TemporaryDirectory(dir=self.root) as folder:
                path=Path(folder)/'ops.db';j=self.journal(path)
                fp=j.fingerprint({});j.claim('one',fp)
                path.rename(Path(folder)/'original');path.touch(mode=0o600)
                args={'fingerprint':({},),'lookup':('one',fp),'claim':('two',fp),
                      'intent':('one',),'finish':('one',{})}[method]
                with self.assertRaises(UnsafeOperation):getattr(j,method)(*args)
                j.close();self.assertEqual(path.read_bytes(),b'')

    def test_boundaries_refuse_ancestor_and_lock_replacement(self):
        folder=self.root/'private';folder.mkdir(mode=0o700)
        j=self.journal(folder/'ops.db')
        folder.rename(self.root/'old');folder.mkdir(mode=0o700)
        with self.assertRaises(UnsafeOperation):j.fingerprint({})
        j.close()
        j=self.journal();lock=Path(str(self.path)+'.lock')
        lock.rename(self.root/'old-lock');lock.touch(mode=0o600)
        with self.assertRaises(UnsafeOperation):j.fingerprint({})

    def test_post_boundary_check_catches_replacement(self):
        j=self.journal();fp=j.fingerprint({});j.claim('one',fp)
        original=j._lookup
        def replace(*args):
            result=original(*args)
            self.path.rename(self.root/'old');self.path.touch(mode=0o600)
            return result
        with patch.object(j,'_lookup',side_effect=replace):
            with self.assertRaises(UnsafeOperation):j.lookup('one',fp)

    def test_aux_symlink_at_boundary(self):
        j=self.journal();target=self.root/'target';target.touch(mode=0o600)
        Path(str(self.path)+'-journal').symlink_to(target)
        with self.assertRaises(UnsafeOperation):j.claim('one',j.salt.hex())

    def test_audit_redacts_and_changes_no_files(self):
        fp=self.seed();before=self.snapshot();connect=sqlite3.connect;seen=[]
        def observe(*args,**kwargs):
            self.assertTrue(kwargs.get('uri'));self.assertTrue(args[0].endswith('?mode=ro'))
            db=connect(*args,**kwargs);db.set_trace_callback(seen.append);return db
        with patch('pymacauto.journal.sqlite3.connect',side_effect=observe):result=Journal.audit(self.path)
        self.assertEqual(self.snapshot(),before)
        encoded=json.dumps(result)
        self.assertNotIn('private-operation-id',encoded);self.assertNotIn('private-value',encoded)
        self.assertNotIn('AXValue',encoded);self.assertNotIn('salt',encoded)
        self.assertEqual(len(result['operations']),1)
        row=result['operations'][0]
        self.assertEqual(set(row),{'operation_id','stage','status','fingerprint'})
        self.assertEqual((row['fingerprint'],row['stage'],row['status']),(fp,'DISPATCH_INTENT','CONFIRMED'))
        self.assertFalse(any('journal_mode' in sql.lower() or sql.startswith(('CREATE','INSERT','UPDATE','DELETE')) for sql in seen),seen)
        self.assertEqual(Journal.audit(self.path),result)

    def test_audit_missing_target_creates_nothing(self):
        missing=self.root/'absent'/'ops.db'
        with self.assertRaises((OSError,UnsafeOperation)):Journal.audit(missing)
        self.assertFalse(missing.parent.exists())
        with self.assertRaises((OSError,UnsafeOperation)):Journal.audit(self.path)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_audit_legacy_without_lock_does_not_create_lock(self):
        self.seed();Path(str(self.path)+'.lock').unlink()  # owned fixture only
        before=self.snapshot();Journal.audit(self.path)
        self.assertEqual(self.snapshot(),before)

    def test_readonly_lookup_and_fingerprint_no_writes(self):
        fp=self.seed();Path(str(self.path)+'.lock').unlink()
        before=self.snapshot();j=Journal(self.path,readonly=True);self.addCleanup(j.close)
        self.assertEqual(j.fingerprint({'AXValue':'private-value'}),fp)
        self.assertEqual(j.lookup('private-operation-id',fp)['status'],'CONFIRMED')
        for method,args in (('claim',('new',fp)),('intent',('private-operation-id',)),('finish',('private-operation-id',{}))):
            with self.subTest(method=method),self.assertRaises(UnsafeOperation):getattr(j,method)(*args)
        j.close();self.assertEqual(self.snapshot(),before)
        self.assertEqual(audit_journal(self.path),Journal.audit(self.path))

    def test_readonly_missing_never_creates(self):
        with self.assertRaises((OSError,UnsafeOperation)):Journal(self.path,readonly=True)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_audit_invalid_schema_and_records(self):
        self.seed()
        for statement in ("UPDATE operations SET stage='unknown'", "UPDATE operations SET fingerprint='bad'",
                          "UPDATE operations SET receipt='{'", "UPDATE meta SET value=X'32' WHERE key='schema'"):
            with self.subTest(statement=statement):
                before=self.path.read_bytes()
                with closing(sqlite3.connect(self.path)) as db:
                    with db:db.execute(statement)
                snapshot=self.snapshot()
                with self.assertRaises(UnsafeOperation):Journal.audit(self.path)
                self.assertEqual(self.snapshot(),snapshot)
                self.path.write_bytes(before)

    def test_audit_rejects_wal_without_creating_sidecars(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as db:db.execute('PRAGMA journal_mode=WAL')
        before=self.snapshot()
        with self.assertRaises(UnsafeOperation):Journal.audit(self.path)
        self.assertEqual(self.snapshot(),before)

    def test_audit_rejects_sidecars_without_modifying_them(self):
        self.seed()
        for suffix in ('-journal','-wal','-shm'):
            with self.subTest(suffix=suffix):
                sidecar=Path(str(self.path)+suffix);sidecar.write_bytes(b'private-sidecar');sidecar.chmod(0o600)
                before=self.snapshot()
                try:
                    with self.assertRaises(UnsafeOperation):Journal.audit(self.path)
                    self.assertEqual(self.snapshot(),before)
                finally:sidecar.unlink()

    def test_insecure_file_hardlink_and_parent_refused(self):
        self.seed();self.path.chmod(0o644)
        with self.assertRaises(UnsafeOperation):Journal(self.path)
        self.path.chmod(0o600)
        os.link(self.path,self.root/'hardlink')
        with self.assertRaises(UnsafeOperation):Journal(self.path)
        folder=self.root/'public';folder.mkdir(mode=0o755);folder.chmod(0o755)
        with self.assertRaises(UnsafeOperation):Journal(folder/'ops.db')

    def test_first_creator_initializes_before_waiting_opener(self):
        worker=r'''
import sys
import pymacauto.journal as module
if sys.argv[2]=='creator':
 original=module.sqlite3.connect
 def pause(*args,**kwargs):
  print('PINNED',flush=True);sys.stdin.read(1)
  return original(*args,**kwargs)
 module.sqlite3.connect=pause
else:
 print('STARTED',flush=True)
j=module.Journal(sys.argv[1]);j.claim(sys.argv[2],j.fingerprint({}));j.close()
'''
        children=[]
        def start(role):
            child=subprocess.Popen([sys.executable,'-u','-c',worker,str(self.path),role],
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            children.append(child)
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout,selectors.EVENT_READ)
                self.assertTrue(selector.select(10),'child readiness timeout')
            return child
        try:
            creator=start('creator');self.assertEqual(creator.stdout.readline().strip(),'PINNED')
            waiter=start('waiter');self.assertEqual(waiter.stdout.readline().strip(),'STARTED')
            # Creator still owns the stable lock while its new DB is empty.
            with selectors.DefaultSelector() as selector:
                selector.register(waiter.stdout,selectors.EVENT_READ)
                self.assertFalse(selector.select(0.1),'opener bypassed initialization lock')
            creator.stdin.write('x');creator.stdin.flush()
            results=[]
            for child in children:
                stdout,stderr=child.communicate(timeout=15)
                results.append((child.returncode,stdout,stderr))
            self.assertTrue(all(r[0]==0 for r in results),results)
            self.assertEqual(len(Journal.audit(self.path)['operations']),2)
        finally:
            for child in children:
                if child.poll() is None:child.kill()
                child.communicate(timeout=5)

    def test_concurrent_first_open_preserves_all_claims(self):
        worker=r'''
import sys
from pymacauto.journal import Journal
print('READY',flush=True);sys.stdin.read(1)
j=Journal(sys.argv[1]);fp=j.fingerprint({'request':sys.argv[2]})
j.claim(sys.argv[2],fp);j.intent(sys.argv[2]);j.close()
'''
        children=[]
        try:
            for i in range(6):
                child=subprocess.Popen([sys.executable,'-u','-c',worker,str(self.path),str(i)],
                                       stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append(child)
            for child in children:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout,selectors.EVENT_READ)
                    self.assertTrue(selector.select(10),'child readiness timeout')
                self.assertEqual(child.stdout.readline().strip(),'READY')
            for child in children:child.stdin.write('x');child.stdin.flush()
            results=[]
            for child in children:
                stdout,stderr=child.communicate(timeout=15)
                results.append((child.returncode,stdout,stderr))
            self.assertTrue(all(r[0]==0 for r in results),results)
            rows=Journal.audit(self.path)['operations']
            self.assertEqual(len(rows),6)
            self.assertTrue(all(r['stage']=='DISPATCH_INTENT' for r in rows))
            self.journal().close()
            self.assertEqual(Journal.audit(self.path)['operations'],rows)
        finally:
            for child in children:
                if child.poll() is None:child.kill()
                child.communicate(timeout=5)


if __name__=='__main__':unittest.main()
