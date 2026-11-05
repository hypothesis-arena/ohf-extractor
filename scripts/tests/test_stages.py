"""Stage stops on synthetic logs/documents, with no real search or model call."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import ohfkit
import search
import stages
from conftest import CC_BY, PARAS, jats, put


@pytest.fixture
def logged(xml_workdir):
    work = {'source_id': 'MED:1', 'pmid': '1', 'pmcid': 'PMC0000001', 'doi': '10.0000/test',
            'title': 'An answering work', 'type': 'Comment; Correction'}
    call = search.Searcher(xml_workdir).call('responses', {'id': 'PMC0000001'}, lambda r: (1, [work], {}))
    return xml_workdir, call


BUILDER = '''import ohfkit
def build(calls, workdir):
    doc = ohfkit.Document('PMC0000001', workdir)
    card = ohfkit.skeleton(budget_counter=lambda: {'model_calls': 0, 'http_requests': 0, 'coverage': 'complete', 'scope': 'invented stage fixture only'}, ident='h_' + calls[0]['call_id'], doc=doc, citation='Test A. A test.',
        citation_title='A test', doi='10.0000/test', topic=['test'], sources={'p1': doc.src(1)}, author_names='Test A')
    card['author']['layers']['core']['statement'] = doc.author(1, 'We propose that X causes Y when recombination stops.')
    INSERT
    return card
'''


def builder(workdir, insertion='pass'):
    path = Path(workdir) / 'build.py'
    path.write_text(BUILDER.replace('INSERT', insertion.replace('\n', '\n    ')))
    return path


def test_close_step_writes_only_log_metadata_without_verdicts(logged):
    workdir, call = logged
    original = (workdir / search.LOG).read_bytes()
    rec = stages.close_step(workdir)
    assert rec['log']['sha256'] == search.sha256(original)
    assert rec['log']['call_count'] == 1
    assert rec['log']['works'][0]['publication_types'] == ['Comment', 'Correction']
    assert rec['log']['works'][0]['call_id'] == call['call_id']
    assert not stages.has_decision(rec)
    assert not (workdir / stages.DRAFT).exists()
    assert (workdir / search.LOG).read_bytes() == original


def test_close_step_preserves_types_in_both_logged_shapes(logged):
    workdir, call = logged
    call['works'][0]['type'] = 'Letter'
    call['works'][0]['pubTypeList'] = {'pubType': ['Comment', 'Correction']}
    (workdir / search.LOG).write_text(json.dumps(call) + '\n')
    assert stages.close_step(workdir)['log']['works'][0]['publication_types'] == ['Comment', 'Correction', 'Letter']


@pytest.mark.parametrize('payload', ['', '{unfinished', '{}\n', '[]\n'])
def test_an_empty_or_partial_log_is_not_a_closed_step(xml_workdir, payload):
    (xml_workdir / search.LOG).write_text(payload)
    with pytest.raises(stages.StageError):
        stages.close_step(xml_workdir)
    assert not (xml_workdir / stages.STEP).exists()


def test_a_step_cannot_be_closed_again_or_smuggle_in_decisions(logged):
    workdir, call = logged
    stages.close_step(workdir)
    original = (workdir / stages.STEP).read_bytes()
    with pytest.raises(search.StepClosedError):
        stages.close_step(workdir)
    assert (workdir / stages.STEP).read_bytes() == original
    call['verdict'] = 'carried'
    other = workdir / 'other'
    other.mkdir()
    (other / search.LOG).write_text(json.dumps(call) + '\n')
    with pytest.raises(stages.StageError, match='decisions'):
        stages.close_step(other)


def test_a_closed_step_blocks_search_before_transport_or_log_write(logged):
    workdir, _ = logged
    stages.close_step(workdir)
    original = (workdir / search.LOG).read_bytes()
    requested = []
    client = search.Searcher(workdir, get=lambda url: requested.append(url))
    for action in [lambda: client.literature('unplanned'),
                   lambda: client.fetch('https://synthetic.invalid/', []),
                   lambda: client.log({'tool': 'extra'})]:
        with pytest.raises(search.StepClosedError):
            action()
    assert requested == []
    assert (workdir / search.LOG).read_bytes() == original


def test_from_log_refuses_missing_or_changed_step_before_running_builder(logged):
    workdir, _ = logged
    path = workdir / 'build.py'
    path.write_text("raise AssertionError('builder must not run')")
    with pytest.raises(stages.StageError, match='missing'):
        stages.build_from_log(path, workdir)
    stages.close_step(workdir)
    with (workdir / search.LOG).open('ab') as file:
        file.write(b'\n')
    with pytest.raises(stages.StageError, match='changed'):
        stages.build_from_log(path, workdir)


def test_from_log_builds_and_freezes_a_separate_first_draft(logged):
    workdir, call = logged
    stop = stages.close_step(workdir)
    rec = stages.build_from_log(builder(workdir), workdir)
    frozen = workdir / stages.DRAFT
    card = json.loads((frozen / 'card.json').read_text())
    assert card['id'] == 'h_' + call['call_id'], 'the builder did not use the written log'
    assert rec['log_sha256'] == stop['log']['sha256']
    assert rec['card_sha256'] == search.sha256((frozen / 'card.json').read_bytes())
    assert rec['content_hash'] == card['content_hash']
    assert rec['kit']['version'] == ohfkit.CONVERTER['version']
    assert rec['kit']['rules_hash'] == card['added']['by']['converter_hash']
    assert stages.check_draft(workdir) == rec
    with pytest.raises(stages.StageError, match='already exists'):
        stages.build_from_log(builder(workdir), workdir)
    assert stages.check_draft(workdir) == rec


@pytest.mark.parametrize('insertion', [
    "import search; search.Searcher(workdir).literature('unplanned')",
    "import search; search.Searcher(workdir).fetch('https://synthetic.invalid/', [])",
    "import urllib.request; urllib.request.urlopen('https://synthetic.invalid/')",
    "import search\ntry:\n    search.Searcher(workdir).literature('caught')\nexcept RuntimeError:\n    pass",
])
def test_from_log_replaces_transport_with_a_raising_stub_even_if_caught(logged, insertion):
    workdir, _ = logged
    stages.close_step(workdir)
    with pytest.raises((search.StepClosedError, stages.StageError)):
        stages.build_from_log(builder(workdir, insertion), workdir)
    assert not (workdir / stages.DRAFT).exists()
    assert not list(workdir.glob('.first-draft-*'))


def test_building_cannot_change_the_fixed_log(logged):
    workdir, _ = logged
    stages.close_step(workdir)
    with pytest.raises(stages.StageError):
        stages.build_from_log(builder(workdir, "(workdir / 'search-log.jsonl').write_text('')"), workdir)
    assert not (workdir / stages.DRAFT).exists()


def test_editing_frozen_draft_bytes_is_detected(logged):
    workdir, _ = logged
    stages.close_step(workdir)
    stages.build_from_log(builder(workdir), workdir)
    path = workdir / stages.DRAFT / 'card.json'
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(stages.StageError, match='changed'):
        stages.check_draft(workdir)


def test_a_draft_refuses_a_nonquotable_main_source_before_saving_body_text(logged):
    workdir, _ = logged
    put(workdir, 'PMC0000001.xml', jats(PARAS, CC_BY.replace('Attribution 4.0', 'Attribution-NonCommercial 4.0')))
    stages.close_step(workdir)
    with pytest.raises(ohfkit.LicenceError):
        stages.build_from_log(builder(workdir), workdir)
    assert not (workdir / stages.DRAFT).exists()
    assert not list(workdir.glob('.first-draft-*'))


@pytest.mark.parametrize('reference_only', [False, True])
def test_a_draft_refuses_a_quote_from_a_nonquotable_secondary_source(logged, reference_only):
    workdir, _ = logged
    put(workdir, 'PMC0000002.xml', jats(['A forbidden quoted sentence.'],
        CC_BY.replace('Attribution 4.0', 'Attribution-NonCommercial 4.0')))
    insertion = """bad = ohfkit.Document('PMC0000002', workdir)
card['added']['sources']['bad'] = bad.src(1)
RESTRICT
card['added']['layers']['core']['scope'] = {'value': 'scope', 'src': 'bad', 'basis_quote': 'A forbidden quoted sentence.'}
""".replace('RESTRICT', "card['added']['sources']['bad'] = ohfkit.reference_only(card['added']['sources']['bad'], 'NC')"
            if reference_only else 'pass')
    stages.close_step(workdir)
    with pytest.raises((ohfkit.LicenceError, stages.StageError)):
        stages.build_from_log(builder(workdir, insertion), workdir)
    assert not (workdir / stages.DRAFT).exists()
    assert not list(workdir.glob('.first-draft-*'))


def test_cli_requires_the_explicit_from_log_mode(logged):
    workdir, _ = logged
    env = dict(os.environ, OHF_MODEL='synthetic-stage-test')
    assert subprocess.run([sys.executable, str(Path(stages.__file__)), 'build', str(builder(workdir)),
                           '--workdir', str(workdir)], capture_output=True).returncode == 2
    assert subprocess.run([sys.executable, str(Path(search.__file__)), 'close-step', '--workdir', str(workdir)],
                           capture_output=True).returncode == 0
    result = subprocess.run([sys.executable, str(Path(stages.__file__)), 'build', str(builder(workdir)),
                             '--from-log', '--workdir', str(workdir)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert stages.check_draft(workdir)


def test_two_builders_cannot_replace_each_others_first_draft(logged):
    workdir, _ = logged
    stages.close_step(workdir)
    env = dict(os.environ, OHF_MODEL='synthetic-stage-test')
    cmd = [sys.executable, str(Path(stages.__file__)), 'build', str(builder(workdir)),
           '--from-log', '--workdir', str(workdir)]
    runs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for _ in range(2)]
    for run in runs:
        run.communicate(timeout=30)
    assert sorted(run.returncode for run in runs) == [0, 1]
    assert stages.check_draft(workdir)


@pytest.mark.parametrize('caught', [False, True], ids=['propagated', 'caught'])
@pytest.mark.parametrize('route', ['opener', 'http.client', 'socket'])
def test_from_log_blocks_ordinary_requests_at_transport_boundaries(logged, monkeypatch, caught, route):
    import http.client
    import io
    import socket
    import urllib.request

    workdir, _ = logged
    stages.close_step(workdir)
    reached = []

    def transport(*args, **kwargs):
        reached.append(True)
        return io.BytesIO(b'synthetic response; no sockets')

    target, method, imports, request = {
        'opener': (urllib.request.OpenerDirector, 'open', 'import urllib.request',
                   "urllib.request.build_opener().open('https://synthetic.invalid/extra')"),
        'http.client': (http.client.HTTPConnection, 'send', 'import http.client',
                        "http.client.HTTPConnection('synthetic.invalid').request('GET', '/extra')"),
        'socket': (socket, 'create_connection', 'import socket',
                   "socket.create_connection(('synthetic.invalid', 443))"),
    }[route]
    monkeypatch.setattr(target, method, transport)
    code = imports + '\n' + request
    if caught:
        code = imports + '\ntry:\n    ' + request + '\nexcept RuntimeError:\n    pass'
    with pytest.raises((search.StepClosedError, stages.StageError)):
        stages.build_from_log(builder(workdir, code), workdir)
    assert reached == []
    assert not (workdir / stages.DRAFT).exists()


def test_closing_waits_for_another_threads_completed_call_and_log_record(logged):
    import threading

    workdir, _ = logged
    entered, release, closing, closed = (threading.Event() for _ in range(4))
    results, errors = [], []

    def callback(responses):
        entered.set()
        assert release.wait(5)
        return 1, [{'pmid': '2', 'type': 'Letter'}], {}

    def call():
        try:
            search.Searcher(workdir).call('responses', {'id': 'PMC0000002'}, callback)
        except BaseException as error:
            errors.append(error)

    def close():
        closing.set()
        try:
            results.append(stages.close_step(workdir))
            closed.set()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=call)
    closer = threading.Thread(target=close)
    worker.start()
    try:
        assert entered.wait(5)
        closer.start()
        assert closing.wait(5)
        assert not closed.wait(0.2), 'close-step returned while the kit call was still active'
    finally:
        release.set()
        worker.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not worker.is_alive() and not closer.is_alive()
    assert not errors, [repr(error) for error in errors]
    assert results[0]['log']['call_count'] == 2
    calls = search.read_log(workdir)
    assert len(calls) == 2 and calls[-1]['ask']['id'] == 'PMC0000002'
    assert results[0]['log']['sha256'] == search.sha256((workdir / search.LOG).read_bytes())


def test_nested_workdirs_have_independent_filesystem_locks(tmp_path):
    import fcntl

    first, second = tmp_path / 'first', tmp_path / 'second'
    with search.store_lock(first):
        with search.store_lock(second):
            for path in (first, second):
                with (path / search.LOCK).open('rb') as probe:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('caught', [False, True], ids=['propagated', 'caught'])
@pytest.mark.parametrize('source', ['new', 'existing'])
def test_socket_creation_and_sendmsg_on_existing_sockets_cannot_publish_a_draft(
        logged, monkeypatch, caught, source):
    import socket

    workdir, _ = logged
    stages.close_step(workdir)
    sent = []

    def sendmsg(self, buffers, *args, **kwargs):
        sent.append(True)
        return sum(map(len, buffers))  # a sentinel, never a syscall or packet

    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wire:
        monkeypatch.setattr(socket, '_ohf_test_wire', wire, raising=False)
        monkeypatch.setattr(socket.socket, 'sendmsg', sendmsg)
        request = ("with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wire:\n"
                   "    wire.sendmsg([b'synthetic'], [], 0, '/synthetic-never-sent')") if source == 'new' else \
                  "socket._ohf_test_wire.sendmsg([b'synthetic'], [], 0, '/synthetic-never-sent')"
        if caught:
            request = 'try:\n    ' + request.replace('\n', '\n    ') + '\nexcept RuntimeError:\n    pass'
        with pytest.raises((search.StepClosedError, stages.StageError)):
            stages.build_from_log(builder(workdir, 'import socket\n' + request), workdir)
    assert sent == []
    assert not (workdir / stages.DRAFT).exists()


@pytest.mark.parametrize('caught', [False, True], ids=['propagated', 'caught'])
@pytest.mark.parametrize('factory', ['socket', 'SocketType', 'socketpair', 'fromfd'])
def test_a_builder_cannot_create_a_socket_even_without_sending(logged, monkeypatch, caught, factory):
    import socket

    workdir, _ = logged
    stages.close_step(workdir)
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as source:
        monkeypatch.setattr(socket, '_ohf_test_source', source, raising=False)
        request = {
            'socket': 'socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).close()',
            'SocketType': 'socket.SocketType(socket.AF_UNIX, socket.SOCK_DGRAM).close()',
            'socketpair': 'a, b = socket.socketpair()\na.close()\nb.close()',
            'fromfd': 'socket.fromfd(socket._ohf_test_source.fileno(), socket.AF_UNIX, socket.SOCK_DGRAM).close()',
        }[factory]
        if caught:
            request = 'try:\n    ' + request.replace('\n', '\n    ') + '\nexcept RuntimeError:\n    pass'
        with pytest.raises((search.StepClosedError, stages.StageError)):
            stages.build_from_log(builder(workdir, 'import socket\n' + request), workdir)
    assert not (workdir / stages.DRAFT).exists()
