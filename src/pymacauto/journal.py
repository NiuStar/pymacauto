"""Private intent journal; uncertain intents are never replayed.

Descriptors pin the checked ancestry and file, not SQLite's pathname opens.
Cooperative locks and before/after checks detect persistent replacements; a
hostile same-user process can still swap paths between SQLite's own syscalls.
This is not an exactly-once transaction with the target UI.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from .errors import UnsafeOperation


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def _identity(info):
    return info.st_dev, info.st_ino


def _private_file(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise UnsafeOperation('Journal file must be a private owned regular file')


class Journal:
    def __init__(self,path,readonly=False):
        self._open(path, readonly=readonly)

    def _open(self,path,readonly):
        self._fds=[];self._chain=[];self._file=None;self._lock=None;self.db=None
        self.path=Path(path).expanduser().absolute()
        if '..' in self.path.parts or not self.path.name:
            raise UnsafeOperation('Journal path must not contain parent traversal')
        self._mutex=threading.RLock();self._readonly=readonly
        try:
            parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
            self._fds.append(parent)
            for name in self.path.parent.parts[1:]:
                try:
                    child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                except FileNotFoundError:
                    if readonly:raise
                    try:os.mkdir(name,0o700,dir_fd=parent)
                    except FileExistsError:pass
                    child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                self._fds.append(child);self._chain.append((parent,name,child));parent=child
            self._parent=parent
            self._check_parent()
            # Never unlink this stable cooperative lock, even after init failure.
            flags=os.O_NOFOLLOW|(os.O_RDONLY if readonly else os.O_RDWR|os.O_CREAT)
            for attempt in range(4):
                try:
                    self._lock=os.open(self.path.name+'.lock',flags,0o600,dir_fd=parent);break
                except FileNotFoundError:
                    if readonly:break
                    self._check_parent()
                    if attempt==3:raise
                    # Native concurrent openat tests reported transient ENOENT.
                    # Retry only name creation, retaining ancestor validation.
                    time.sleep(.01)
            if self._lock is not None:
                self._fds.append(self._lock);_private_file(os.fstat(self._lock))
                self._acquire_lock(readonly)
            try:
                self._check_paths()
                created=False
                if not readonly:
                    try:
                        self._file=os.open(self.path.name,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=parent)
                        created=True
                    except FileExistsError:pass
                if self._file is None:
                    self._file=os.open(self.path.name,(os.O_RDONLY if readonly else os.O_RDWR)|os.O_NOFOLLOW,dir_fd=parent)
                self._fds.append(self._file)
                self._check_paths()
                if readonly:
                    # WAL readers may create shm/wal, and hot rollback recovery
                    # would write. Audit accepts only a clean rollback database.
                    if os.pread(self._file,2,18)!=b'\x01\x01':
                        raise UnsafeOperation('Audit requires a clean rollback journal')
                    self._check_aux(absent=True)
                self._check_paths()
                self.db=sqlite3.connect(self.path.as_uri()+'?mode='+('ro' if readonly else 'rw'),uri=True,timeout=2,check_same_thread=False)
                self._check_paths()
                if readonly:
                    self.db.execute('PRAGMA query_only=ON')
                    self.db.execute('BEGIN')
                else:
                    self.db.execute('PRAGMA journal_mode=DELETE')
                    self.db.execute('PRAGMA synchronous=EXTRA')
                self._check_paths()
                if created:
                    # Only the exclusive creator under the stable lock may DDL.
                    with self.db:
                        self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
                        self.db.executemany('INSERT INTO meta VALUES (?,?)',[('salt',os.urandom(32)),('schema',b'1')])
                        self.db.execute('CREATE TABLE operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, stage TEXT NOT NULL, receipt TEXT)')
                self._validate_schema()
                if not readonly:os.fsync(parent)
                self._check_paths()
            finally:
                if self._lock is not None:fcntl.flock(self._lock,fcntl.LOCK_UN)
        except BaseException:
            self.close()
            raise

    def _acquire_lock(self,readonly):
        deadline=time.monotonic()+2
        while True:
            try:
                fcntl.flock(self._lock,(fcntl.LOCK_SH if readonly else fcntl.LOCK_EX)|fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic()>=deadline:raise UnsafeOperation('Journal lock timeout')
                time.sleep(.01)

    def _check_parent(self):
        for parent,name,child in self._chain:
            info=os.stat(name,dir_fd=parent,follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or _identity(info)!=_identity(os.fstat(child)):
                raise UnsafeOperation('Journal ancestor identity changed')
        info=os.fstat(self._parent)
        if info.st_uid!=os.getuid() or info.st_mode & 0o077:
            raise UnsafeOperation('Journal parent must be a private owned directory')

    def _check_aux(self,absent=False):
        for suffix in ('-journal','-wal','-shm'):
            try:info=os.stat(self.path.name+suffix,dir_fd=self._parent,follow_symlinks=False)
            except FileNotFoundError:continue
            _private_file(info)
            if absent:raise UnsafeOperation('Audit requires no SQLite auxiliary files')

    def _check_paths(self):
        self._check_parent()
        for fd,name in ((self._file,self.path.name),(self._lock,self.path.name+'.lock')):
            if fd is None:continue
            pinned=os.fstat(fd);_private_file(pinned)
            info=os.stat(name,dir_fd=self._parent,follow_symlinks=False);_private_file(info)
            if _identity(info)!=_identity(pinned):raise UnsafeOperation('Journal identity changed')
        self._check_aux(absent=self._readonly)

    @contextmanager
    def _boundary(self):
        with self._mutex:
            if self.db is None:raise UnsafeOperation('Journal is closed')
            if self._lock is not None:self._acquire_lock(self._readonly)
            try:
                self._check_paths()
                yield
                self._check_paths()
            finally:
                if self._lock is not None:fcntl.flock(self._lock,fcntl.LOCK_UN)

    def _validate_schema(self):
        tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables!={'meta','operations'}:raise UnsafeOperation('Incomplete journal schema')
        expected={'meta':[('key','TEXT',0,1),('value','BLOB',1,0)],
                  'operations':[('id','TEXT',0,1),('fingerprint','TEXT',1,0),('stage','TEXT',1,0),('receipt','TEXT',0,0)]}
        for table,columns in expected.items():
            actual=[(r[1],r[2],r[3],r[5]) for r in self.db.execute('PRAGMA table_info('+table+')')]
            if actual!=columns:raise UnsafeOperation('Invalid journal schema')
        if self.db.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
            raise UnsafeOperation('Unexpected journal schema objects')
        meta=dict(self.db.execute('SELECT key,value FROM meta'))
        if set(meta)!={'schema','salt'} or meta['schema']!=b'1':raise UnsafeOperation('Unknown journal version')
        self.salt=meta['salt']
        if not isinstance(self.salt,bytes) or len(self.salt)!=32:raise UnsafeOperation('Invalid journal salt')
        if self.db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise UnsafeOperation('Corrupt journal')

    @staticmethod
    def _record(operation_id,row):
        if not isinstance(operation_id,str) or not operation_id:
            raise UnsafeOperation('Invalid operation ID')
        if not isinstance(row[0],str) or len(row[0])!=64 or any(c not in '0123456789abcdef' for c in row[0]):
            raise UnsafeOperation('Invalid journal fingerprint')
        if row[1] not in ('PREPARED','DISPATCH_INTENT'):raise UnsafeOperation('Unknown journal stage')
        if row[2] is not None:
            try:receipt=json.loads(row[2])
            except (ValueError,TypeError) as exc:raise UnsafeOperation('Invalid journal receipt') from exc
            if not isinstance(receipt,dict) or receipt.get('operation_id')!=operation_id or receipt.get('status') not in ('NOT_DISPATCHED','DISPATCHED_UNCONFIRMED','CONFIRMED'):
                raise UnsafeOperation('Invalid journal receipt')
            attempted=receipt.get('dispatch_attempted');verified=receipt.get('verified');attempts=receipt.get('attempts')
            if type(attempted) is not bool or type(verified) is not bool or type(attempts) is not int:
                raise UnsafeOperation('Invalid receipt types')
            if row[1]=='PREPARED' and (attempted or verified or receipt['status']!='NOT_DISPATCHED' or attempts!=0):
                raise UnsafeOperation('Prepared intent cannot confirm dispatch')
            if row[1]=='DISPATCH_INTENT' and (not attempted or attempts!=1 or receipt['status']=='NOT_DISPATCHED' or (receipt['status']=='CONFIRMED')!=verified):
                raise UnsafeOperation('Receipt contradicts dispatch intent')
            return receipt
        return {'operation_id':operation_id,'status':'DISPATCHED_UNCONFIRMED' if row[1]=='DISPATCH_INTENT' else 'RECOVERY_REQUIRED',
                'dispatch_attempted':row[1]=='DISPATCH_INTENT','verified':False,'attempts':1 if row[1]=='DISPATCH_INTENT' else 0,
                'error':'IncompleteJournal','recovered':True}

    def fingerprint(self,request):
        with self._boundary():return hmac.new(self.salt,canonical(request),hashlib.sha256).hexdigest()

    def _lookup(self,operation_id,fingerprint):
        row=self.db.execute('SELECT fingerprint,stage,receipt FROM operations WHERE id=?',(operation_id,)).fetchone()
        if row is None:return None
        receipt=self._record(operation_id,row)
        if not hmac.compare_digest(row[0],fingerprint):raise UnsafeOperation('Operation ID conflicts with its original request')
        return receipt

    def lookup(self,operation_id,fingerprint):
        with self._boundary():return self._lookup(operation_id,fingerprint)

    def claim(self,operation_id,fingerprint):
        if self._readonly:raise UnsafeOperation('Read-only journal cannot claim operations')
        self._record(operation_id,(fingerprint,'PREPARED',None))
        with self._boundary():
            self.db.execute('BEGIN IMMEDIATE')
            try:
                result=self._lookup(operation_id,fingerprint)
                if result is None:self.db.execute('INSERT INTO operations VALUES (?,?,?,NULL)',(operation_id,fingerprint,'PREPARED'))
                self._check_paths();self.db.commit();return result
            except BaseException:self.db.rollback();raise

    def intent(self,operation_id):
        if self._readonly:raise UnsafeOperation('Read-only journal cannot dispatch')
        with self._boundary(),self.db:
            changed=self.db.execute('UPDATE operations SET stage=? WHERE id=? AND stage=? AND receipt IS NULL',('DISPATCH_INTENT',operation_id,'PREPARED')).rowcount
            if changed!=1:raise UnsafeOperation('Dispatch intent transition refused')
            self._check_paths()

    def finish(self,operation_id,receipt):
        if self._readonly:raise UnsafeOperation('Read-only journal cannot finish operations')
        with self._boundary(),self.db:
            row=self.db.execute('SELECT fingerprint,stage,receipt FROM operations WHERE id=?',(operation_id,)).fetchone()
            if row is None:raise UnsafeOperation('Missing journal operation')
            encoded=canonical(receipt).decode();self._record(operation_id,(row[0],row[1],encoded))
            self.db.execute('UPDATE operations SET receipt=? WHERE id=?',(encoded,operation_id))
            self._check_paths()

    @classmethod
    def audit(cls,path):
        """Read-only clean rollback snapshot; IDs are salted opaque digests.

        Never creates directories, locks, databases, sidecars or schema, and
        never changes journal_mode. WAL/hot journals require operator recovery.
        Only the explicit projection below may leave the private database.
        """
        journal=cls.__new__(cls)
        try:
            journal._open(path,readonly=True)
            with journal._boundary():
                operations=[]
                for operation_id,fp,stage,receipt in journal.db.execute('SELECT id,fingerprint,stage,receipt FROM operations ORDER BY id'):
                    record=journal._record(operation_id,(fp,stage,receipt))
                    operations.append({'operation_id':hmac.new(journal.salt,canonical(operation_id),hashlib.sha256).hexdigest(),
                                       'fingerprint':fp,'stage':stage,'status':record['status']})
                return {'schema':1,'operations':operations}
        finally:journal.close()

    def close(self):
        if self.db is not None:self.db.close();self.db=None
        for fd in reversed(self._fds):os.close(fd)
        self._fds=[]


def audit_journal(path):
    """Return Journal.audit's redacted, read-only schema-1 snapshot."""
    return Journal.audit(path)
