"""Explicit opt-in rubric/2 preparation and model-field history, separate from defaults.

Pure caller API: prepare -> freeze (optional file) -> externally obtained results
-> merge -> carry/check/export. No checker/provider implementation or native CLI.
Use mode="rubric-2" and a modality_scopes map keyed by atom JSON pointer:
{pointer: {"atom_pointer": pointer, "statement_pointer": pointer+"/statement",
           "scope": "whole_atom"}}. This is an explicit caller assertion of scope,
not a machine determination of linguistic atomicity. Native OHF 1.3/1.4 is refused.
The ordinary 1.0/1.1 renderer preserves atom/parent/core conditions; dependency
and entity projections it cannot represent are refused. Direction retains the
ordinary renderer's target/quote encoding, not the native projection profile.
No current native reader or normative full-card acceptance is implied.

The format, records and rubric identity live ONLY in the dedicated sidecar; do
not copy its records into the closed card schema or mix its history with the
ordinary entailment-ledger.json. restore accepts only original same-card v2
sidecars, never archived card verdicts or a legacy ledger. merge requires a
response envelope with checker, rubric, input_sha256,
request_sha256 and results; never infer that envelope from bare archived results.
These fields must be supplied by the result producer for the request it received.
This is a binding assertion, not authentication against a dishonest producer.
Outputs are append-only attestations; eligibility is checked against current
preparation at each read.
The supplied modality scopes are question context, never extra passage evidence.

This sidecar is not a full card/schema/scientific validator. Supplied results are
caller attestations, not authenticated model execution. Native activation is HOLD.
"""
import copy
from pathlib import Path
import re

import check_ledger as ledger_v1
import checker_io as io
import entailment as legacy
import ohfkit
from projection_binding import sha, canonical, value_sha256

RUBRIC = 'ohf-entailment-rubric/2'
PROMPT = Path(__file__).resolve().parents[1] / 'references/entailment-rubric-2.md'
PROMPT_SHA256 = 'sha256:f6fd3f094679357042ef6a2eb4e573bcadfafb9cc97b05bae1ed0cd005dc3880'
CHECKER = {'name': 'ohf-entailment-check', 'version': '2.0.0', 'prompt_sha256': PROMPT_SHA256}
FORMAT = 'ohf-entailment-rubric-ledger/1'
PACKET = 'ohf-entailment-rubric-input/1'
MODE = 'rubric-2'
MODALITY = re.compile(r'^/added/layers/core/atoms/(\d+)/modality$')
ATOM_FIELDS = {'id', 'statement', 'parent_ref', 'operator', 'context_override', 'src',
               'claim_type', 'role', 'modality', 'requires', 'contradicts', 'triple'}


class InputRefused(ValueError):
    """Preparation failure; never an entailment verdict."""
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


def refuse(code, detail):
    raise InputRefused(code, detail)



def _same_json(left, right):
    """JSON type-preserving equality: true, 1, 1.0 and "1" stay distinct."""
    return canonical(left) == canonical(right)


def _append_entry(ledger, key, entry, note):
    """Preserve history with the same type-exact identity used by its reader."""
    history = ledger['entries'].setdefault(key, [])
    if note:
        ledger['notes'][ledger_v1.note_sha256(note)] = note
    if any(_same_json(old, entry) for old in history):
        return False
    history.append(copy.deepcopy(entry))
    history.sort(key=lambda old: old['checked_at'])
    return True


def unbox(value):
    return value.get('value') if isinstance(value, dict) else value


def prompt():
    raw = PROMPT.read_bytes()
    if sha(raw) != PROMPT_SHA256:
        refuse('INPUT_REFUSED_RUBRIC_PIN', 'rubric bytes differ from the pinned identity')
    return raw


def require_mode(card, mode):
    if mode != MODE:
        refuse('INPUT_REFUSED_MODE', 'explicit mode="rubric-2" is required')
    if card.get('standard_version') not in ('1.0', '1.1'):
        refuse('INPUT_REFUSED_NATIVE_HOLD', 'only ordinary OHF 1.0/1.1; native activation needs a matching profile review')
    if not isinstance(card.get('id'), str) or not card['id'].strip():
        refuse('INPUT_REFUSED_CARD', 'one owned card id is required')


def atom_context(card, index, scopes):
    core = card['added']['layers']['core']
    atoms = core.get('atoms', [])
    atom = atoms[index]
    pointer = f'/added/layers/core/atoms/{index}'
    expected = {'atom_pointer': pointer, 'statement_pointer': pointer + '/statement', 'scope': 'whole_atom'}
    if not _same_json(scopes.get(pointer), expected):
        refuse('INPUT_REFUSED_MODALITY_SCOPE', 'declare exact atom/statement pointers and whole_atom scope')
    # Conservative supported legacy subset. Never shorten a dependency/entity
    # projection to a statement: those shapes require a separately reviewed reader.
    parents, seen, current = [], set(), atom
    while True:
        if not isinstance(current, dict) or set(current) - ATOM_FIELDS:
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'unsupported or malformed atom context')
        statement = unbox(current.get('statement'))
        if not isinstance(statement, str) or not statement.strip():
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'nonempty exact atomic statement required')
        if any(current.get(k) for k in ('requires', 'contradicts', 'triple')):
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'dependency/entity projection is unsupported in this ordinary reader')
        if unbox(current.get('operator')) in ('AND', 'OR', 'XOR'):
            refuse('INPUT_REFUSED_COMPOUND_TARGET', 'explicit logical group requires separately bound questions')
        if unbox(current.get('operator')) is not None:
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'unknown logical operator')
        parents.append(copy.deepcopy({k: v for k, v in current.items() if k != 'modality'}))
        parent = unbox(current.get('parent_ref'))
        if parent is None:
            break
        if not isinstance(parent, str) or parent in seen:
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'cyclic or invalid parent reference')
        seen.add(parent)
        matches = [a for a in atoms if isinstance(a, dict) and unbox(a.get('id')) == parent]
        if len(matches) != 1:
            refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'unresolved or ambiguous parent context')
        current = matches[0]
    if card['added']['layers'].get('entities'):
        refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'external entity definitions require a matching context renderer')
    context = {k: copy.deepcopy(core.get(k)) for k in
               ('kind', 'scope', 'context', 'assumptions', 'falsification_condition')}
    return {'atom': parents[0], 'parents': parents[1:], 'core_context': context}, expected


def prepare(card, docs, *, mode, modality_scopes):
    """Build all ordinary model items; caller explicitly attests whole-atom scope.

    The source objects are the existing local document interface; no source is
    fetched. Resolver items remain on their existing deterministic route.
    """
    require_mode(card, mode)
    if not isinstance(modality_scopes, dict):
        refuse('INPUT_REFUSED_MODALITY_SCOPE', 'explicit per-atom scope map required')
    atoms = card['added']['layers']['core'].get('atoms', [])
    if not isinstance(atoms, list) or any(not isinstance(a, dict) for a in atoms):
        refuse('INPUT_REFUSED_MISSING_ATOM_CONTEXT', 'atom list is malformed')
    for i, atom in enumerate(atoms):
        if 'modality' in atom:
            atom_context(card, i, modality_scopes)
            if not isinstance(atom['modality'], dict) or 'value' not in atom['modality']:
                refuse('INPUT_REFUSED_MODALITY_SCOPE', 'modality node lacks its value')
    items = legacy.checker_items(legacy.build(card, docs))
    bindings, used_scopes = {}, set()
    nodes = dict(ledger_v1.sourced(card))
    for item in items:
        match = MODALITY.fullmatch(item['pointer'])
        if match:
            index = int(match[1])
            atom, scope = atom_context(card, index, modality_scopes)
            modality = item['value']
            if modality not in ('speculative', 'proposed', 'likely', 'claimed_shown'):
                refuse('INPUT_REFUSED_MODALITY_SCOPE', 'unknown modality value')
            item['value'] = {'modality': modality, 'atomic_claim': atom, 'modality_scope': scope}
            used_scopes.add(scope['atom_pointer'])
        src = nodes[item['pointer']]['src']
        record = card['added']['sources'][src]
        doc = docs.get(record['source'])
        if doc is None or not isinstance(getattr(doc, 'sha', None), str) or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', doc.sha):
            refuse('INPUT_REFUSED_SOURCE_BINDING', 'local source version hash required for every item')
        bindings[ledger_v1.key_of(item)] = {'source_key': src, 'record': copy.deepcopy(record),
                                           'document_sha256': doc.sha}
    if set(modality_scopes) != used_scopes:
        refuse('INPUT_REFUSED_MODALITY_SCOPE', 'scope map contains missing or foreign atom questions')
    if not items or any(set(x) != {'id', 'pointer', 'basis', 'value', 'source_passage'}
                        or not isinstance(x['source_passage'], str) or not x['source_passage'].strip()
                        for x in items):
        refuse('INPUT_REFUSED_SOURCE_BINDING', 'nonempty exact five-field passage items required')
    raw = io.encoded(items)
    # Exclude only derived entailment records/hash from the question envelope.
    # Context/source/assessment/version edits cannot be rescued by metadata rehash.
    question = copy.deepcopy(card)
    question.pop('content_hash', None)
    question.get('added', {}).get('integrity', {}).pop('entailment', None)
    request = prompt() + b'\n\n' + raw
    return {'format': PACKET, 'mode': MODE, 'card_id': card['id'],
            'question_card_sha256': value_sha256(question), 'rubric': RUBRIC,
            'checker': copy.deepcopy(CHECKER), 'items': items, 'sources': bindings,
            'modality_scopes': copy.deepcopy(modality_scopes),
            'input_sha256': sha(raw), 'request_sha256': sha(request),
            'request_utf8': request.decode('utf-8')}


def freeze(card, docs, path, *, mode, modality_scopes):
    """Exclusive durable packet, containing the exact visible prompt + 2LF + items."""
    packet = prepare(card, docs, mode=mode, modality_scopes=modality_scopes)
    io.write_once(path, io.encoded(packet))
    return packet


def new_ledger(card):
    return {'format': FORMAT, 'card_id': card['id'], 'entries': {}, 'notes': {}}


def history_envelope(card, ledger):
    if (not isinstance(ledger, dict) or ledger.get('format') != FORMAT
            or not _same_json(ledger.get('card_id'), card.get('id'))
            or not isinstance(ledger.get('entries'), dict) or not isinstance(ledger.get('notes'), dict)):
        refuse('INPUT_REFUSED_LEDGER', 'dedicated card-owned v2 sidecar required; no legacy migration')
    for key, history in ledger['entries'].items():
        if not isinstance(key, str) or not isinstance(history, list):
            refuse('INPUT_REFUSED_LEDGER', 'invalid history container')
        for entry in history:
            if (not isinstance(entry, dict) or entry.get('verdict') not in ledger_v1.RANK
                    or not isinstance(entry.get('checked_at'), str)):
                refuse('INPUT_REFUSED_LEDGER', 'invalid attested history entry')


def entry_binding(packet, item):
    return {'checker': copy.deepcopy(packet['checker']), 'rubric': packet['rubric'],
            'question_card_sha256': packet['question_card_sha256'],
            'request_sha256': packet['request_sha256'], 'input_sha256': packet['input_sha256'],
            'value_sha256': value_sha256(item['value']),
            'passage_sha256': ledger_v1.passage_sha256(item['source_passage']),
            'source_binding_sha256': value_sha256(packet['sources'][ledger_v1.key_of(item)])}


def active(packet, item, ledger):
    """ALL model fields require exact checker/rubric/question/source identity."""
    if (packet.get('format') != PACKET or packet.get('mode') != MODE
            or not _same_json(packet.get('checker'), CHECKER)
            or not _same_json(packet.get('rubric'), RUBRIC)):
        return []
    expected = entry_binding(packet, item)
    return [e for e in ledger['entries'].get(ledger_v1.key_of(item), [])
            if all(_same_json(e.get(k), v) for k, v in expected.items())]


def selected_records(packet, ledger):
    records, rest = [], []
    for item in packet['items']:
        e = ledger_v1.choose(active(packet, item, ledger))
        if e is None:
            rest.append(copy.deepcopy(item))
            continue
        record = {k: copy.deepcopy(e[k]) for k in ('checker', 'rubric', 'checked_at', 'verdict')}
        record.update(pointer=item['pointer'], basis=item['basis'])
        if e.get('note_sha256'):
            note = ledger['notes'].get(e['note_sha256'])
            if not isinstance(note, str) or ledger_v1.note_sha256(note) != e['note_sha256']:
                refuse('INPUT_REFUSED_LEDGER', 'note binding differs')
            record['note'] = note
        if record['verdict'] != 'entails' and not record.get('note'):
            refuse('INPUT_REFUSED_LEDGER', 'non-entails history lacks its note')
        records.append(record)
    return {'mode': MODE, 'records': records, 'rest': rest,
            'scientific_truth_evaluated': False, 'full_card_validated': False}


def merge(card, docs, packet, response, ledger, *, mode):
    """Append explicitly supplied results. No model execution/authentication claim.

    Rebuild the entire exact packet before changing history; never stamp current
    identity onto archived card verdicts. Cards and supplied packet are not edited.
    """
    require_mode(card, mode)
    history_envelope(card, ledger)
    if not isinstance(packet, dict):
        refuse('INPUT_REFUSED_STALE_INPUT', 'one frozen packet object is required')
    expected = prepare(card, docs, mode=mode, modality_scopes=packet.get('modality_scopes'))
    if not _same_json(packet, expected):
        refuse('INPUT_REFUSED_STALE_INPUT', 'question, passage, source or checker/rubric identity changed')
    # Canonical JSON equality retains types but ignores object key order. The
    # actual checker wire does not: reserialize the supplied items, never trust
    # stored request/hash fields to describe a changed item tree. Verify all of
    # these bytes BEFORE any append, without rewriting card, packet or response.
    raw = io.encoded(packet['items'])
    request = prompt() + b'\n\n' + raw
    if (sha(raw) != packet['input_sha256'] or sha(request) != packet['request_sha256']
            or request != packet['request_utf8'].encode('utf-8')):
        refuse('INPUT_REFUSED_STALE_INPUT', 'actual item/request bytes differ from the frozen binding')
    # A raw ID/verdict list says nothing about which rubric/request returned it.
    # Require an explicit producer attestation for the complete frozen request;
    # never infer it from an output's row IDs or stamp new identity on old output.
    identity = {k: packet[k] for k in ('checker', 'rubric', 'request_sha256', 'input_sha256')}
    if (not isinstance(response, dict) or set(response) != set(identity) | {'results'}
            or any(not _same_json(response.get(k), v) for k, v in identity.items())):
        refuse('INPUT_REFUSED_RESULT_BINDING', 'explicit matching checker/rubric/input/request response required')
    results = response['results']
    io.valid_results(packet['items'], results)
    pending = []
    at = io.now()
    for item, result in zip(packet['items'], results):
        entry = {**entry_binding(packet, item), 'checked_at': at, 'verdict': result['verdict']}
        note = result.get('note')
        if note:
            entry['note_sha256'] = ledger_v1.note_sha256(note)
        pending.append((ledger_v1.key_of(item), entry, note))
    for key, entry, note in pending:
        _append_entry(ledger, key, entry, note)
    return selected_records(packet, ledger)


def carry(card, docs, ledger, *, mode, modality_scopes):
    """Return eligible v2 records/rest without changing card, ledger or timestamps."""
    packet = prepare(card, docs, mode=mode, modality_scopes=modality_scopes)
    history_envelope(card, ledger)
    return selected_records(packet, ledger)


def restore(card, docs, ledger, archived_ledger, *, mode, modality_scopes):
    """Copy original v2 histories verbatim; no card-only/legacy verdict restoration."""
    packet = prepare(card, docs, mode=mode, modality_scopes=modality_scopes)
    history_envelope(card, ledger)
    history_envelope(card, archived_ledger)
    staged = copy.deepcopy(ledger)
    for key, history in archived_ledger['entries'].items():
        for entry in history:
            note = archived_ledger['notes'].get(entry.get('note_sha256'))
            if entry.get('note_sha256') and (not isinstance(note, str)
                    or ledger_v1.note_sha256(note) != entry['note_sha256']):
                refuse('INPUT_REFUSED_LEDGER', 'archived note binding differs')
            _append_entry(staged, key, entry, note)
    result = selected_records(packet, staged)
    ledger.update(staged)
    return result


def check(card, docs, ledger, *, mode, modality_scopes):
    """Binding coverage only; no schema, source truth, ENT or full-card PASS."""
    result = carry(card, docs, ledger, mode=mode, modality_scopes=modality_scopes)
    return {**result, 'status': 'NEEDS_CHECK' if result['rest'] else 'BOUND_ATTESTATIONS_ONLY'}


def export(card, docs, ledger, path, *, mode, modality_scopes):
    result = check(card, docs, ledger, mode=mode, modality_scopes=modality_scopes)
    if result['rest']:
        refuse('INPUT_REFUSED_STALE_INPUT', 'some current questions lack bound v2 attestations')
    io.write_once(path, io.encoded(ledger))
    return result
