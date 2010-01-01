#!/usr/bin/env python
import sys, os, subprocess, errno, zlib, time
import hashsplit, git, options
from helpers import *

BLOB_LWM = 8192*2
BLOB_MAX = BLOB_LWM*2
BLOB_HWM = 1024*1024


class Buf:
    def __init__(self):
        self.data = ''
        self.start = 0

    def put(self, s):
        #log('oldsize=%d+%d adding=%d\n' % (len(self.data), self.start, len(s)))
        if s:
            self.data = buffer(self.data, self.start) + s
            self.start = 0
            
    def peek(self, count):
        return buffer(self.data, self.start, count)
    
    def eat(self, count):
        self.start += count

    def get(self, count):
        v = buffer(self.data, self.start, count)
        self.start += count
        return v

    def used(self):
        return len(self.data) - self.start


def splitbuf(buf):
    b = buf.peek(buf.used())
    ofs = hashsplit.splitbuf(b)
    if ofs:
        buf.eat(ofs)
        return buffer(b, 0, ofs)
    return None


def blobiter(files):
    for f in files:
        b = 1
        while b:
            b = f.read(BLOB_HWM)
            if b:
                yield b
    yield '' # EOF indicator


def autofiles(filenames):
    if not filenames:
        yield sys.stdin
    else:
        for n in filenames:
            yield open(n)
            
    
def hashsplit_iter(f):
    ofs = 0
    buf = Buf()
    fi = blobiter(f)
    blob = 1

    eof = 0
    lv = 0
    while blob or not eof:
        if not eof and (buf.used() < BLOB_LWM or not blob):
            bnew = fi.next()
            if not bnew: eof = 1
            #log('got %d, total %d\n' % (len(bnew), buf.used()))
            buf.put(bnew)

        blob = splitbuf(buf)
        if eof and not blob:
            blob = buf.get(buf.used())
        if not blob and buf.used() >= BLOB_MAX:
            blob = buf.get(BLOB_MAX)  # limit max blob size
        if not blob and not eof:
            continue

        if blob:
            yield (ofs, len(blob), git.hash_blob(blob))
            ofs += len(blob)
          
        nv = (ofs + buf.used())/1000000
        if nv != lv:
            log('%d\t' % nv)
            lv = nv


optspec = """
bup split [-t] [filenames...]
--
b,blobs    output a series of blob ids
t,tree     output a tree id
c,commit   output a commit id
n,name=    name of backup set to update (if any)
bench      print benchmark timings to stderr
"""
o = options.Options('bup split', optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

if not (opt.blobs or opt.tree or opt.commit or opt.name):
    log("bup split: use one or more of -b, -t, -c, -n\n")
    o.usage()

start_time = time.time()
shalist = []

ofs = 0
last_ofs = 0
for (ofs, size, sha) in hashsplit_iter(autofiles(extra)):
    #log('SPLIT @ %-8d size=%-8d\n' % (ofs, size))
    if opt.blobs:
        print sha
            
    # this silliness keeps chunk filenames "similar" when a file changes
    # slightly.
    bm = BLOB_MAX
    while 1:
        cn = ofs / bm * bm
        #log('%x,%x,%x,%x\n' % (last_ofs,ofs,cn,bm))
        if cn > last_ofs or ofs == last_ofs: break
        bm /= 2
    last_ofs = cn
    shalist.append(('100644', 'bup.chunk.%016x' % cn, sha))
tree = git.gen_tree(shalist)
if opt.tree:
    print tree
if opt.commit or opt.name:
    msg = 'Generated by command:\n%r' % sys.argv
    ref = opt.name and ('refs/heads/%s' % opt.name) or None
    commit = git.gen_commit_easy(ref, tree, msg)
    if opt.commit:
        print commit

secs = time.time() - start_time
if opt.bench:
    log('\nbup: %.2fkbytes in %.2f secs = %.2f kbytes/sec\n'
        % (ofs/1024., secs, ofs/1024./secs))