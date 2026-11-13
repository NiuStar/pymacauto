"""Private SQLite intent journal. Uncertain intents are never replayed.

A committed intent precedes every protected mutation. It is not an atomic
transaction with the target UI and cannot establish exactly-once business effects.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
from .errors import UnsafeOperation


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


class Journal:
    def __init__(self,path):
        self.path=Path(path).expanduser().absolute()
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        parent=self.path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode & 0o077:
            raise UnsafeOperation('Journal parent must be a private owned directory')
        try:
            fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600);created=True
        except FileExistsError:
            fd=os.open(self.path,os.O_RDWR|os.O_NOFOLLOW);created=False
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_mode & 0o077:
                raise UnsafeOperation('Journal file must be a private owned regular file')
            if (info.st_dev,info.st_ino)!=(self.path.stat().st_dev,self.path.stat().st_ino):
                raise UnsafeOperation('Journal identity changed')
        finally:os.close(fd)
        self.db=sqlite3.connect(str(self.path),timeout=2,check_same_thread=False)
        try:
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=EXTRA')
            if created:
                with self.db:
                    self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
                    self.db.execute('INSERT INTO meta VALUES (?,?)',('salt',os.urandom(32)))
                    self.db.execute('INSERT INTO meta VALUES (?,?)',('schema',b'1'))
                    self.db.execute('CREATE TABLE operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, stage TEXT NOT NULL, receipt TEXT)')
            else:
                tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables!={'meta','operations'}:raise UnsafeOperation('Incomplete journal schema')
                if [r[1] for r in self.db.execute('PRAGMA table_info(operations)')]!=['id','fingerprint','stage','receipt']:
                    raise UnsafeOperation('Invalid operation schema')
                if self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()!=(b'1',):
                    raise UnsafeOperation('Unknown journal version')
                if self.db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise UnsafeOperation('Corrupt journal')
            salt=self.db.execute('SELECT value FROM meta WHERE key=?',('salt',)).fetchone()
            if salt is None:raise UnsafeOperation('Journal salt missing')
            self.salt=salt[0]
            if not isinstance(self.salt,bytes) or len(self.salt)!=32:raise UnsafeOperation('Invalid journal salt')
            directory=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except BaseException:self.db.close();raise
    def fingerprint(self,request):return hmac.new(self.salt,canonical(request),hashlib.sha256).hexdigest()
    def lookup(self,operation_id,fingerprint):
        row=self.db.execute('SELECT fingerprint,stage,receipt FROM operations WHERE id=?',(operation_id,)).fetchone()
        if row is None:return None
        if not hmac.compare_digest(row[0],fingerprint):raise UnsafeOperation('Operation ID conflicts with its original request')
        if row[1] not in ('PREPARED','DISPATCH_INTENT'):raise UnsafeOperation('Unknown journal stage')
        if row[2] is not None:
            receipt=json.loads(row[2])
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
    def claim(self,operation_id,fingerprint):
        # BEGIN IMMEDIATE makes cross-process same-ID reservations exclusive.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result=self.lookup(operation_id,fingerprint)
            if result is None:self.db.execute('INSERT INTO operations VALUES (?,?,?,NULL)',(operation_id,fingerprint,'PREPARED'))
            self.db.commit();return result
        except BaseException:self.db.rollback();raise
    def intent(self,operation_id):
        with self.db:
            changed=self.db.execute('UPDATE operations SET stage=? WHERE id=? AND stage=?',('DISPATCH_INTENT',operation_id,'PREPARED')).rowcount
            if changed!=1:raise UnsafeOperation('Dispatch intent transition refused')
    def finish(self,operation_id,receipt):
        with self.db:self.db.execute('UPDATE operations SET receipt=? WHERE id=?',(canonical(receipt).decode(),operation_id))
    def close(self):self.db.close()
