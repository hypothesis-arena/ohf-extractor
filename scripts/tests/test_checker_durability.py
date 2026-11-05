"""Invented local bytes and fake callbacks only; no real crash or external calls."""
import os
import stat
from pathlib import Path
import types

import pytest

import ohfkit
if ohfkit.standard_line() != '1.4':
    pytest.skip('Native profile conformance requires its explicit OHF 1.4 checkout', allow_module_level=True)

import checker_io as io
import projection_binding as projection


def packet(tmp_path):
    inp=tmp_path/'input.json';out=tmp_path/'output.json'
    prompt=b'Invented glyph instructions.'
    checker={'name':'invented','version':'1','prompt_sha256':projection.sha(prompt)}
    config={'kind':'injected_fake'}
    items=[{'id':'r1','pointer':'/invented','basis':'src','value':'blue square',
            'source_passage':'An invented blue square.'}]
    io.freeze(items,inp,prompt,checker,config,{'card_id':'h_invented'})
    return inp,out


def label(fd, directory):
    info=os.fstat(fd)
    if stat.S_ISDIR(info.st_mode):return 'directory'
    for p in directory.iterdir():
        current=p.lstat()
        if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino):return p.name
    raise AssertionError('unexpected file descriptor in durability test')


def fake_callback(calls, events=None):
    def fake(request,configuration):
        calls.append(1)
        if events is not None:events.append('callback')
        return {'request_sha256':projection.sha(request),
                'configuration_sha256':projection.value_sha256(configuration),
                'result_bytes':io.encoded([{'id':'r1','verdict':'entails'}])}
    return fake


def test_exclusive_write_flushes_and_syncs_file_then_directory(tmp_path,monkeypatch):
    target=tmp_path/'bytes.json';raw=b'Invented local bytes.';events=[]
    real_sync,real_mode=os.fsync,os.fchmod
    def mode(fd,value):
        real_mode(fd,value);events.append('mode')
    def sync(fd):
        name=label(fd,tmp_path);events.append(name)
        if name!='directory':
            assert target.read_bytes()==raw  # visible through another fd before fsync
            assert stat.S_IMODE(target.stat().st_mode)==0o444
        return real_sync(fd)
    monkeypatch.setattr(os,'fchmod',mode);monkeypatch.setattr(os,'fsync',sync)
    io.write_once(target,raw)
    assert events==['mode','bytes.json','directory']


@pytest.mark.parametrize('fault',['bytes.json','directory'])
def test_write_barrier_fault_preserves_evidence_and_refuses_replacement(tmp_path,monkeypatch,fault):
    target=tmp_path/'bytes.json';raw=b'Invented bytes retained after failure.'
    real_sync=os.fsync;seen=[]
    def sync(fd):
        name=label(fd,tmp_path);seen.append(name)
        if name==fault:raise OSError('invented '+fault+' fsync failure')
        return real_sync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    with pytest.raises(ValueError) as error:io.write_once(target,raw)
    assert isinstance(error.value.__cause__,OSError) and fault in seen
    assert target.read_bytes()==raw and stat.S_IMODE(target.stat().st_mode)==0o444
    monkeypatch.setattr(os,'fsync',real_sync)
    with pytest.raises(ValueError):io.write_once(target,b'replacement refused')
    assert target.read_bytes()==raw


def test_all_saved_prerequisites_and_dispatch_sync_before_callback(tmp_path,monkeypatch):
    inp,out=packet(tmp_path);events=[];calls=[];real_sync=os.fsync
    def sync(fd):
        events.append(label(fd,tmp_path));return real_sync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    io.run(inp,out,fake_callback(calls,events))
    assert calls==[1]
    assert events==['input.json','input.json.request','input.json.binding.json','directory',
                    'input.json.dispatch.json','directory','callback',
                    'output.json','directory','output.json.binding.json','directory']


@pytest.mark.parametrize('fault',[
    'input-file','input-directory','dispatch-file','dispatch-directory',
    'output-file','output-directory','receipt-file','receipt-directory'])
def test_phase_barrier_faults_stop_with_preserved_evidence_and_no_callback_replay(tmp_path,monkeypatch,fault):
    inp,out=packet(tmp_path);calls=[];real_sync=os.fsync;directories=0;seen=[]
    names={'input.json':'input-file','input.json.dispatch.json':'dispatch-file',
           'output.json':'output-file','output.json.binding.json':'receipt-file'}
    def sync(fd):
        nonlocal directories
        name=label(fd,tmp_path)
        if name=='directory':
            directories+=1
            phase={1:'input-directory',2:'dispatch-directory',3:'output-directory',4:'receipt-directory'}[directories]
        else:phase=names.get(name,name)
        seen.append(phase)
        if phase==fault:raise OSError('invented '+fault+' fsync failure')
        return real_sync(fd)
    original={p:p.read_bytes() for p in io.paths(inp)}
    monkeypatch.setattr(os,'fsync',sync)
    with pytest.raises(ValueError) as error:io.run(inp,out,fake_callback(calls))
    assert isinstance(error.value.__cause__,OSError) and fault in seen
    before_callback=fault.startswith(('input-','dispatch-'))
    assert calls==([] if before_callback else [1])
    assert all(p.read_bytes()==raw for p,raw in original.items())
    dispatch=io.dispatch_path(inp)
    if fault.startswith('input-'):
        assert not dispatch.exists() and not out.exists()
    else:
        assert dispatch.is_file()
        saved=dispatch.read_bytes()
        monkeypatch.setattr(os,'fsync',real_sync)
        with pytest.raises(ValueError):io.run(inp,tmp_path/'different-output.json',fake_callback(calls))
        assert dispatch.read_bytes()==saved and calls==([] if before_callback else [1])
    if before_callback:assert not out.exists()
    else:assert out.is_file()  # partial result evidence retained, never a successful return


def test_simulated_crash_after_dispatch_blocks_fresh_module_replay(tmp_path):
    class SimulatedCrash(BaseException):pass
    inp,out=packet(tmp_path);calls=[]
    def crash(request,configuration):
        calls.append(1);raise SimulatedCrash('invented abrupt checker interruption')
    with pytest.raises(SimulatedCrash):io.run(inp,out,crash)
    dispatch=io.dispatch_path(inp);saved=dispatch.read_bytes()
    assert not out.exists()
    # Reconstruct module state from the exact tested source without a process or pyc.
    source=Path(io.__file__).read_bytes()
    fresh=types.ModuleType('invented_fresh_checker_io');fresh.__file__=io.__file__
    exec(compile(source,io.__file__,'exec'),fresh.__dict__)
    assert projection.sha(source)==projection.sha(Path(io.__file__).read_bytes())
    with pytest.raises(ValueError):fresh.run(inp,tmp_path/'after-restart.json',fake_callback(calls))
    assert calls==[1] and dispatch.read_bytes()==saved


# Replay the original independent review's five grouped stimuli, with the
# positive completed packet used for duplicate/pair controls after fault refusal.
def test_original_review_group_1_barrier_spy_before_callback(tmp_path,monkeypatch):
    inp,out=packet(tmp_path);events=[];calls=[];real_sync=os.fsync
    def sync(fd):events.append('fsync');return real_sync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    io.run(inp,out,fake_callback(calls,events))
    assert calls==[1] and events.index('callback')>=2
    assert events[:events.index('callback')]==['fsync']*6


def test_original_review_group_2_global_fsync_fault_never_calls_checker(tmp_path,monkeypatch):
    inp,out=packet(tmp_path);calls=[];barriers=[]
    def fail(fd):barriers.append(fd);raise OSError('original invented durability fault')
    monkeypatch.setattr(os,'fsync',fail)
    with pytest.raises(ValueError):io.run(inp,out,fake_callback(calls))
    assert barriers and calls==[] and not out.exists()


def test_original_review_group_3_normal_duplicate_dispatch_refuses(tmp_path):
    inp,out=packet(tmp_path);calls=[];io.run(inp,out,fake_callback(calls))
    with pytest.raises(ValueError):io.run(inp,tmp_path/'different-output.json',fake_callback(calls))
    assert calls==[1]


def test_original_review_group_4_saved_pair_positive_then_mutation_refusal(tmp_path):
    inp,out=packet(tmp_path);io.run(inp,out,fake_callback([]))
    items=io.strict_json(inp.read_bytes());results=io.strict_json(out.read_bytes())
    meta=io.strict_json(io.paths(inp)[2].read_bytes())
    pair=io.load_pair(inp,out,meta['checker'],meta['envelope'])
    pair.verify_arguments(items,results)
    pair.results[0]['verdict']='no'
    with pytest.raises(ValueError):pair.verify_arguments(items,pair.results)


def test_original_review_group_5_alias_and_duplicate_result_refuse(tmp_path):
    inp,out=packet(tmp_path);alias=tmp_path/'alias.json';alias.symlink_to(inp)
    with pytest.raises(ValueError):io.read(alias)
    items=io.strict_json(inp.read_bytes())
    with pytest.raises(ValueError):io.valid_results(items,[{'id':'r1','verdict':'entails'}]*2)
