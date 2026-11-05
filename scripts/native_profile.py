"""Explicit local native renderer profile and one schema+ledger validation entrypoint.

No CLI, source fetch, provider, process or checker implementation. Selection and
proof metadata remain external to scientific-card wire fields.
"""
import copy
import hashlib
import importlib.metadata
import rfc8785
import argparse
import builtins
import datetime
import json
import math
import os
import pathlib
from pathlib import Path
import re
import sys
import types
import xml.etree.ElementTree as ET

import jsonschema
import jsonschema.exceptions

import native_ledger as ledger_api
import checker_io as io
import native_entailment as entailment
import ohfkit
import projection_binding as projection

DEFINITION = Path(__file__).resolve().parents[1] / 'references/native-renderer-profile-4.json'
DEFINITION_RAW_SHA256 = 'sha256:80b8c026c959b415758c1b0d3ccb2d26a62ba78a50888cd8fb25b90e0202cd46'
DEFINITION_SHA256 = 'sha256:c964ce88b31374062cbebf6e801259f3f85533244633d3d5642cc7bab9124db7'
PROFILE_ID = 'ohf-native-relational@1'
EPOCH = 2
DEPENDENCIES = DEFINITION.with_name('native-profile-dependencies-4.json')
DEPENDENCIES_SHA256 = 'sha256:f130de4169f95e28aa15e81861301f1c7aa473cf2ec16a382806b91f7e665edf'


def dependency_pins():
    raw = io.read(DEPENDENCIES)
    if projection.sha(raw) != DEPENDENCIES_SHA256:
        raise ValueError('PROFILE dependency manifest differs')
    return io.strict_json(raw)['files']


PASSAGE = re.compile(r'^/added/layers/(?:core/(?:statement|scope|kind|atoms/\d+/(?:statement|claim_type|modality|role))|'
                     r'predictions/\d+/(?:population|endpoint|direction|horizon)|'
                     r'evidence/lines/\d+/(?:direction|indirectness|sample_size|endpoint_kind))$')
DERIVE = re.compile(r'^/added/layers/predictions/\d+/derives_from_atom_refs$')


def selection():
    raw = io.read(DEFINITION)
    if projection.sha(raw) != DEFINITION_RAW_SHA256:
        raise ValueError('PROFILE definition pin differs')
    if projection.value_sha256(io.strict_json(raw)) != DEFINITION_SHA256:
        raise ValueError('PROFILE canonical definition digest differs')
    return {'id': PROFILE_ID, 'epoch': EPOCH, 'definition_sha256': DEFINITION_SHA256}


def _is_profile(selected):
    expected = selection()
    return (type(selected) is dict and selected.keys() == expected.keys()
            and all(type(selected[key]) is type(value) and selected[key] == value
                    for key, value in expected.items()))


def require_profile(selected):
    if not _is_profile(selected):
        raise ValueError('UNSUPPORTED_PROFILE: missing, wrong or stale profile/epoch')
    runtime_identity()
    projection.reference()
    root = Path(os.environ['OHF_REPO']).resolve()
    for path, digest in dependency_pins().items():
        if projection.sha(io.read(root / path)) != digest:
            raise ValueError('PROFILE dependency pin differs: ' + path)
    return root


def _validators(selected):
    """Private source loader; all bytes captured and verified before any execution.

    Data reads use the same snapshots. No tools package initializer, bytecode,
    ambient helper module or fallback file participates in this namespace.
    """
    root = require_profile(selected)
    pins = dependency_pins()
    snapshots = {name: io.read(root / name) for name in pins}
    if any(projection.sha(raw) != pins[name] for name, raw in snapshots.items()):
        raise ValueError('PROFILE dependency snapshot differs')

    class CapturedPath(type(Path())):
        def read_bytes(self):
            try:
                name = self.resolve().relative_to(root).as_posix()
                return snapshots[name]
            except (ValueError, KeyError) as error:
                raise ValueError('PROFILE uncaptured dependency read') from error

        def read_text(self, encoding=None, errors=None):
            return self.read_bytes().decode(encoding or 'utf-8', errors or 'strict')

    import hashlib
    modules = {'argparse': argparse, 'pathlib': types.SimpleNamespace(Path=CapturedPath),
               'json': json, 'math': math, 'datetime': datetime, 're': re,
               'jsonschema': jsonschema, 'jsonschema.exceptions': jsonschema.exceptions,
               'rfc8785': rfc8785, 'copy': copy, 'hashlib': hashlib, 'os': os,
               'sys': types.SimpleNamespace(path=[], stderr=sys.stderr)}

    def source_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in modules:
            raise ValueError('PROFILE unsupported validator dependency: ' + name)
        return modules[name]

    for name in ('strict_dates', 'strict_json', 'content_hash', 'check_ledger',
                 'check_gaps', 'check_completeness', 'validate', 'check_refs'):
        rel = 'tools/' + name + '.py'
        module = types.ModuleType('ohf_native_verified_' + name)
        module.__file__ = str(root / rel)
        module.__dict__['__builtins__'] = {**vars(builtins), '__import__': source_import}
        exec(compile(snapshots[rel], module.__file__, 'exec'), module.__dict__)
        modules[name] = module
    return modules, snapshots


def schema_errors(card, selected):
    modules, snapshots = _validators(selected)
    validator = modules['validate']
    schema = io.strict_json(snapshots['schema/hypothesis-1.schema.json'])
    return [validator.pointer(e) + ': ' + e.message for e in validator.validation_errors(schema, card)]


def card_checks(card, selected):
    modules, snapshots = _validators(selected)
    validator = modules['validate']
    data = lambda name: io.strict_json(snapshots[name])
    schema = data('schema/hypothesis-1.schema.json')
    errors = ['SCHEMA: ' + validator.pointer(e) + ': ' + e.message
              for e in validator.validation_errors(schema, card)]
    report = {'errors': errors, 'warnings': [], 'schema_valid': not errors}
    if errors:
        return report
    if card.get('content_hash') != modules['content_hash'].content_hash(card):
        errors.append('CONTENT_HASH: card differs')
    refs = modules['check_refs'].check(card)
    gaps = modules['check_gaps'].check(card, data('spec/gap-path-policy.json'),
                                     data('spec/field-catalogue.json'), data('spec/mapping.json'),
                                     schema=schema)
    errors.extend('REFS: ' + str(e) for e in refs['errors'])
    errors.extend('GAPS: ' + str(e) for e in gaps['errors'])
    report.update(warnings=refs['warnings'], review_required=gaps['review_required'],
                  completeness=refs['completeness'])
    return report


def _only(node, keys, where):
    if not isinstance(node, dict) or set(node) - set(keys):
        raise ValueError('UNSUPPORTED_SHAPE: ' + where)


def _value(node):
    return node.get('value') if isinstance(node, dict) else node


def card_conditions(card):
    """Exact typed same-card identifier resolution, never scientific entailment."""
    layers = card['added']['layers']
    atoms = {_value(a.get('id')): a for a in layers['core'].get('atoms', [])}
    predictions = {_value(p.get('id')): p for p in layers['predictions']}
    identifiers = [_value(a.get('id')) for a in layers['core'].get('atoms', [])] + [
        _value(p.get('id')) for p in layers['predictions']]
    if any(not isinstance(i, str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('CARD_CONDITION: missing or ambiguous typed identifier')
    conditions = []
    for index, prediction in enumerate(layers['predictions']):
        refs = _value(prediction.get('derives_from_atom_refs'))
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or any(r not in atoms for r in refs):
            raise ValueError('CARD_CONDITION: derive refs must name existing added atoms')
        conditions.append({'pointer': f'/added/layers/predictions/{index}/derives_from_atom_refs',
                           'class': 'card', 'atom_refs': copy.deepcopy(refs),
                           'atom_values_sha256': projection.value_sha256([atoms[r] for r in refs])})
    for index, line in enumerate(layers['evidence'].get('lines', [])):
        ref = _value(line.get('target_ref'))
        if ref not in atoms and ref not in predictions:
            raise ValueError('CARD_CONDITION: target must name an added atom or prediction')
        target = projection.target_statement(card, line)
        projection.require_resolved(target)
        conditions.append({'pointer': f'/added/layers/evidence/lines/{index}/target_ref', 'class': 'card',
                           'target_ref': ref, 'target_sha256': projection.value_sha256(target)})
    return conditions


def supported(card, selected):
    require_profile(selected)
    if card.get('standard_version') != '1.4':
        raise ValueError('UNSUPPORTED_VERSION: only selected schema 1.4')
    if (card['added']['by']['converter_hash'] != ohfkit.rules_hash()
            or card['added']['by'].get('converter_version') != ohfkit.CONVERTER['version']
            or card['added']['by'].get('converter') != ohfkit.CONVERTER['name']):
        raise ValueError('PROFILE_CONVERTER_BINDING: card must name this exact candidate rules')
    layers = card['added']['layers']
    for key in ('mechanism', 'provenance', 'appendix'):
        if layers[key]:
            raise ValueError('UNSUPPORTED_SHAPE: nonempty added ' + key)
    _only(layers['profile'], ('domain',), 'profile')
    if layers['profile'].get('domain') != ['none']:
        raise ValueError('UNSUPPORTED_SHAPE: profile.domain')
    _only(layers['core'], ('statement', 'scope', 'kind', 'atoms'), 'core')
    for atom in layers['core'].get('atoms', []):
        _only(atom, ('id', 'statement', 'claim_type', 'modality', 'role'), 'atom')
        if not isinstance(atom.get('id'), str):
            raise ValueError('UNSUPPORTED_SHAPE: sourced atom identifier')
    for prediction in layers['predictions']:
        _only(prediction, ('id', 'population', 'endpoint', 'direction', 'horizon', 'derives_from_atom_refs'), 'prediction')
    _only(layers['evidence'], ('lines',), 'evidence')
    for line in layers['evidence'].get('lines', []):
        _only(line, ('id', 'target_ref', 'quote', 'src', 'direction', 'indirectness', 'sample_size', 'endpoint_kind'), 'line')
    return card_conditions(card)


def document_from_bytes(raw, pmcid, retrieved):
    """Pure native JATS reader from supplied local bytes; never calls fetch."""
    if not isinstance(raw, bytes) or len(raw) > io.MAX_BYTES:
        raise ValueError('SOURCE_BINDING: bounded local XML bytes required')
    if not isinstance(pmcid, str) or re.fullmatch(r'PMC[0-9]+', pmcid) is None:
        raise ValueError('SOURCE_BINDING: exact document identifier required')
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, LookupError, ValueError) as error:
        raise ValueError('SOURCE_BINDING: invalid local JATS XML') from error
    doc = ohfkit.Document.__new__(ohfkit.Document)
    doc.pmcid, doc.url, doc.file = pmcid, ohfkit.EPMC.format(pmcid), pmcid+'.xml'
    doc.sha, doc.retrieved, doc.root = projection.sha(raw), retrieved, root
    doc.paragraphs = [ohfkit.norm(''.join(p.itertext())) for p in root.iter('p')]
    doc.permissions = ohfkit.permissions_text(ohfkit.article_permissions(root))
    doc.profile_xml_bytes = raw
    return doc


def _bound_document(doc):
    raw = getattr(doc, 'profile_xml_bytes', None)
    if not isinstance(raw, bytes):
        raise ValueError('SOURCE_BINDING: original local XML bytes required')
    if not isinstance(getattr(doc, 'root', None), ET.Element) or not isinstance(getattr(doc, 'paragraphs', None), list):
        raise ValueError('SOURCE_BINDING: invalid native JATS reader state')
    checked = document_from_bytes(raw, doc.pmcid, doc.retrieved)
    if (checked.sha != doc.sha or checked.url != doc.url or checked.file != doc.file
            or checked.paragraphs != doc.paragraphs
            or ET.tostring(checked.root) != ET.tostring(doc.root)):
        raise ValueError('SOURCE_BINDING: native document differs from original XML bytes')


def build(card, docs, selected):
    """Actual native rendering/passages; classified card refs never become passages."""
    conditions = supported(card, selected)
    api = _validators(selected)[0]['check_ledger']
    items = []
    used = {card['added']['sources'][node['src']]['source'] for pointer, node in ledger_api.sourced(card)
            if PASSAGE.fullmatch(pointer)}
    if len(used) != 1 or set(docs) != used:
        raise ValueError('UNSUPPORTED_SOURCE: one exact card-owned local document required')
    for pointer, node in ledger_api.sourced(card):
        classification = api.check_class(card, pointer)
        if DERIVE.fullmatch(pointer):
            if classification != 'card':
                raise ValueError('PROFILE field-class pin differs for derive reference')
            continue
        if not PASSAGE.fullmatch(pointer) or classification != 'passage':
            raise ValueError('UNSUPPORTED_FIELD_CLASS: ' + pointer)
        source = card['added']['sources'][node['src']]
        doc = docs.get(source['source'])
        if type(doc) is not ohfkit.Document or doc.url != source['source']:
            raise ValueError('UNSUPPORTED_SOURCE: missing exact native local Document')
        if source['source'] != ohfkit.EPMC.format(doc.pmcid):
            raise ValueError('UNSUPPORTED_SOURCE: document identity')
        _bound_document(doc)
        if source['accessed_at'] != doc.retrieved:
            raise ValueError('SOURCE_BINDING: source retrieval stamp differs')
        if doc.sha != card['author']['source']['source_text_sha256']:
            raise ValueError('SOURCE_BINDING: local document hash differs')
        paragraph = ohfkit.para_number(source['locator'])
        if paragraph is None or source['locator'] != doc.locator(paragraph):
            raise ValueError('UNSUPPORTED_SOURCE: exact native JATS paragraph locator required')
        value = ledger_api.checked_value(card, pointer, node)
        item = {'pointer': pointer, 'basis': 'src', 'value': value,
                'source_passage': entailment.passage(card, docs, node['src'])}
        items.append(item)
        if 'basis_quote' in node:
            items.append({**item, 'basis': 'basis_quote', 'source_passage': node['basis_quote']})
    if not items:
        raise ValueError('UNSUPPORTED_SHAPE: no passage items')
    for line in card['added']['layers']['evidence'].get('lines', []):
        record = card['added']['sources'][line['src']]
        doc = docs[record['source']]
        paragraph = ohfkit.para_number(record['locator'])
        if paragraph is None or record['locator'] != doc.locator(paragraph):
            raise ValueError('UNSUPPORTED_SOURCE: exact finding locator required')
        doc.check(paragraph, line['quote'])
    return [{'id': f'r{i}', **x} for i, x in enumerate(items, 1)], conditions


def roster(items):
    return [{'pointer': x['pointer'], 'basis': x['basis']} for x in items]


def runtime_identity():
    """Versioned validation runtime; module origins are included in the CI receipt."""
    versions = {'jsonschema': '4.26.0', 'rfc8785': '0.1.4', 'attrs': '26.1.0',
                'jsonschema-specifications': '2025.9.1', 'referencing': '0.37.0',
                'rpds-py': '2026.9.1', 'typing_extensions': '4.16.0'}
    try:
        matching = all(importlib.metadata.version(name) == version for name, version in versions.items())
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError('PROFILE_RUNTIME: required dependency unavailable') from error
    if sys.version_info[:2] != (3, 12) or not matching:
        raise ValueError('PROFILE_RUNTIME: pinned Python/dependencies required')
    modules = {'jsonschema': jsonschema, 'rfc8785': rfc8785}
    return {'python': sys.version, 'packages': versions,
            'module_sha256': {name: projection.sha(Path(module.__file__).read_bytes())
                              for name, module in modules.items()}}


def source_bindings(card, docs, items):
    nodes = dict(ledger_api.sourced(card))
    bindings = {}
    for item in items:
        source = card['added']['sources'][nodes[item['pointer']]['src']]
        doc = docs[source['source']]
        bindings[ledger_api.key_of(item)] = {
            'source': source['source'], 'source_text_sha256': doc.sha,
            'locator_sha256': projection.sha(source['locator'].encode('utf-8')),
            'accessed_at': source['accessed_at']}
    return bindings


def contract_identity():
    """Acyclic source/version identity, distinct from a scientific target hash."""
    return {'format': 'ohf-native-profile-binding/2', 'standard_commit': projection.STANDARD_COMMIT,
            'definition_raw_sha256': DEFINITION_RAW_SHA256,
            'definition_sha256': DEFINITION_SHA256, 'dependency_manifest_sha256': DEPENDENCIES_SHA256,
            'schema_sha256': dependency_pins()['schema/hypothesis-1.schema.json'],
            'target_projection': projection.TARGET_PROJECTION,
            'target_module_sha256': projection.STANDARD_MODULE_SHA256,
            'converter': dict(ohfkit.CONVERTER), 'converter_rules_sha256': ohfkit.rules_hash(),
            'runtime': runtime_identity()}


def freeze(card, docs, selected, path, configuration):
    errors = card_checks(card, selected)['errors']
    if errors:
        raise ValueError('; '.join(errors))
    if card.get('content_hash') != ohfkit.content_hash(card):
        raise ValueError('PROFILE card hash differs')
    items, _conditions = build(card, docs, selected)
    config = copy.deepcopy(configuration)
    if (not isinstance(config, dict) or config.get('kind') != 'injected_fake'
            or any(key in config for key in ('renderer_profile', 'item_roster_sha256', 'profile_contract', 'source_bindings'))):
        raise ValueError('PROFILE requires explicit unambiguous checker configuration')
    config.update(renderer_profile=copy.deepcopy(selected), item_roster_sha256=projection.value_sha256(roster(items)),
                  profile_contract=contract_identity(), source_bindings=source_bindings(card, docs, items))
    return io.freeze(items, path, entailment.PROMPT.read_bytes(), entailment.current_checker(), config,
                     entailment.input_envelope(card))


def _profile_proof(proof, selected, card_id):
    meta = proof['input']
    config = meta['configuration']
    actual_roster = [{'pointer': r['pointer'], 'basis': r['basis']} for r in meta['item_manifest']]
    sources = config.get('source_bindings', {})
    if (not _is_profile(config.get('renderer_profile')) or config.get('kind') != 'injected_fake'
            or config.get('profile_contract') != contract_identity()
            or not isinstance(sources, dict) or set(sources) != {ledger_api.key_of(x) for x in actual_roster}
            or any(not isinstance(x, dict) or set(x) != {'source','source_text_sha256','locator_sha256','accessed_at'}
                   for x in sources.values())
            or meta.get('checker') != entailment.current_checker()
            or meta.get('envelope', {}).get('converter_rules_sha256') != ohfkit.rules_hash()
            or meta.get('envelope', {}).get('card_id') != card_id
            or config.get('item_roster_sha256') != projection.value_sha256(actual_roster)
            or len({(r['pointer'], r['basis']) for r in actual_roster}) != len(actual_roster)
            or any(not PASSAGE.fullmatch(r['pointer']) for r in actual_roster)):
        raise ValueError('PROFILE_PROOF: stale epoch, missing profile or wrong frozen item roster')


def _eligible(item, ledger, selected, card_id, current_sources):
    proofs = ledger.get('checker_io_proofs', {})
    active = ledger_api.active(ledger.get('entries', {}).get(ledger_api.key_of(item), []),
                               ledger_api.value_sha256(item['value']),
                               ledger_api.passage_sha256(item['source_passage']))
    eligible = []
    for entry in active:
        binding = entry.get('checker_binding', {})
        proof = proofs.get(binding.get('result_binding_sha256'))
        if not proof or not projection.valid_binding(item, entry) or not io.binding_proven(item, entry, proofs):
            raise ValueError('PROFILE_PROOF: missing or damaged original selected proof')
        _profile_proof(proof, selected, card_id)
        if proof['input']['configuration']['source_bindings'][ledger_api.key_of(item)] != current_sources[ledger_api.key_of(item)]:
            raise ValueError('SOURCE_BINDING: source-version/locator/stamp migration requires an explicit contract; no history relabel')
        eligible.append(entry)
    return active, eligible


def _selected_records(card, docs, selected, ledger, items):
    current_sources = source_bindings(card, docs, items)
    nodes = dict(ledger_api.sourced(card))
    records, rest = [], []
    for item in items:
        _active, eligible = _eligible(item, ledger, selected, card['id'], current_sources)
        view = {**ledger, 'entries': {ledger_api.key_of(item): eligible}}
        floor = ledger_api.not_before(card, nodes[item['pointer']])
        record = entailment.shown_record(item, view, (), floor)
        if record is None or (floor and record['checked_at'] < floor):
            rest.append(item)
        else:
            records.append(record)
    return records, rest


def _stamp(card, docs, selected, ledger, items, conditions):
    card['content_hash'] = ohfkit.content_hash(card)
    stamped = ledger_api.new_ledger(card, ledger['entries'], ledger['notes'], ledger.get('checker_io_proofs'))
    stamped.update(renderer_profile=copy.deepcopy(selected), item_roster=roster(items), card_conditions=conditions,
                   profile_contract=contract_identity(), source_bindings=source_bindings(card, docs, items))
    ledger.clear(); ledger.update(stamped)


def merge(card, docs, selected, input_path, output_path, ledger):
    errors = card_checks(card, selected)['errors']
    if errors:
        raise ValueError('; '.join(errors))
    items, conditions = build(card, docs, selected)
    if ((ledger.get('entries') and not _is_profile(ledger.get('renderer_profile')))
            or ('renderer_profile' in ledger and not _is_profile(ledger['renderer_profile']))):
        raise ValueError('PROFILE_LEDGER: no automatic legacy or other-profile migration')
    pair = io.load_pair(input_path, output_path, entailment.current_checker(), entailment.input_envelope(card))
    _profile_proof(pair.proof(), selected, card['id'])
    if pair.items != items or pair.proof()['input']['configuration']['source_bindings'] != source_bindings(card, docs, items):
        raise ValueError('PROFILE_ROSTER: input differs from actual complete selected producer/source version')
    # No partial in-memory publication on a malformed existing proof or result.
    work_card, work_ledger = copy.deepcopy(card), copy.deepcopy(ledger)
    entailment.merge(work_card, pair.items, pair.results, docs, work_ledger, io_pair=pair, built_items=items)
    records, rest = _selected_records(work_card, docs, selected, work_ledger, items)
    if rest:
        raise ValueError('PROFILE_PROOF: returned pair does not bind every current item')
    work_card['added']['integrity'] = {'entailment': records}
    _stamp(work_card, docs, selected, work_ledger, items, conditions)
    result = validate_bundle(work_card, work_ledger, docs, selected)
    if result['status'] != 'PASS':
        raise ValueError('PROFILE merge refused: ' + '; '.join(result['errors']))
    card.clear(); card.update(work_card);ledger.clear();ledger.update(work_ledger)
    return ledger



def _ledger_json_containers(ledger):
    """Check JSON container boundaries without rewriting history or proofs.

    Missing members remain subject to the existing semantic/proof checks.
    Unexpected programming exceptions are not converted into input failures.
    """
    def object_at(value, path):
        if not isinstance(value, dict):
            raise ValueError('PROFILE_LEDGER_JSON: ' + path + ' must be an object')
        return value

    def object_member(node, key, path):
        return object_at(node[key], path + '.' + key) if key in node else {}

    def object_array(value, path):
        if not isinstance(value, list):
            raise ValueError('PROFILE_LEDGER_JSON: ' + path + ' must be an array')
        for index, member in enumerate(value):
            object_at(member, path + '[' + str(index) + ']')

    object_at(ledger, 'ledger')
    entries = object_member(ledger, 'entries', 'ledger')
    object_member(ledger, 'notes', 'ledger')
    proofs = object_member(ledger, 'checker_io_proofs', 'ledger')
    for key, history in entries.items():
        path = 'ledger.entries[' + repr(key) + ']'
        if not isinstance(key, str):
            raise ValueError('PROFILE_LEDGER_JSON: ledger.entries keys must be strings')
        object_array(history, path)
        for index, entry in enumerate(history):
            binding = object_member(entry, 'checker_binding', path + '[' + str(index) + ']')
            for name in ('checker', 'input_envelope', 'result'):
                object_member(binding, name, path + '[' + str(index) + '].checker_binding')
    for key, proof in proofs.items():
        path = 'ledger.checker_io_proofs[' + repr(key) + ']'
        object_at(proof, path)
        meta = object_member(proof, 'input', path)
        object_member(proof, 'dispatch', path)
        result = object_member(proof, 'result', path)
        config = object_member(meta, 'configuration', path + '.input')
        object_member(meta, 'envelope', path + '.input')
        object_member(meta, 'checker', path + '.input')
        sources = object_member(config, 'source_bindings', path + '.input.configuration')
        for source_key, source in sources.items():
            object_at(source, path + '.input.configuration.source_bindings[' + repr(source_key) + ']')
        if 'item_manifest' in meta:
            object_array(meta['item_manifest'], path + '.input.item_manifest')
        if 'result_manifest' in result:
            object_array(result['result_manifest'], path + '.result.result_manifest')


def validate_bundle(card, ledger, docs, selected):
    """The sole selected full entrypoint: schema AND actual native items/proofs.

    PASS certifies this local structural/binding contract, never scientific truth.
    """
    result = {'entrypoint': 'native_profile.validate_bundle/1', 'status': 'REFUSE',
              'schema_valid': False, 'native_binding_valid': False,
              'scientific_truth_evaluated': False, 'checker_evidence': 'synthetic_fake_only', 'errors': []}
    try:
        checks = card_checks(card, selected)
        errors = checks['errors']
        result['schema_valid'] = checks['schema_valid']
        result['warnings'] = checks['warnings']
        result['review_required'] = checks.get('review_required', [])
        # Retain the structural diagnostic unchanged; it is not scientific completeness.
        if 'completeness' in checks:
            result['completeness'] = copy.deepcopy(checks['completeness'])
        if errors:
            result['errors'] = errors
            return result
        _ledger_json_containers(ledger)
        items, conditions = build(card, docs, selected)
        if (not _is_profile(ledger.get('renderer_profile')) or ledger.get('profile_contract') != contract_identity()
                or ledger.get('item_roster') != roster(items)
                or ledger.get('source_bindings') != source_bindings(card, docs, items)
                or ledger.get('card_conditions') != conditions):
            raise ValueError('PROFILE_LEDGER: profile/epoch/current roster/card conditions differ')
        records = card['added']['integrity']['entailment']
        if len(records) != len(items) or {ledger_api.key_of(r) for r in records} != {ledger_api.key_of(x) for x in items}:
            raise ValueError('PROFILE_ROSTER: missing, duplicate or extra card entailment item')
        proofs = ledger.get('checker_io_proofs', {})
        view = copy.deepcopy(ledger)
        for key, history in ledger.get('entries', {}).items():
            pointer, basis = key.rsplit('|', 1)
            if not PASSAGE.fullmatch(pointer) or basis not in ('src', 'basis_quote'):
                raise ValueError('PROFILE_ROSTER: unsupported extra ledger item')
            for entry in history:
                binding = entry.get('checker_binding')
                if binding:
                    proof = proofs.get(binding.get('result_binding_sha256'))
                    if proof is None:
                        raise ValueError('PROFILE_PROOF: missing historical frozen proof')
                    if 'renderer_profile' in proof['input']['configuration']:
                        _profile_proof(proof, selected, card['id'])
                        if not io.binding_proven({'pointer': pointer, 'basis': basis}, entry, proofs):
                            raise ValueError('PROFILE_PROOF: extra or damaged historical item binding')
        # Every active support requires original selected-profile IO, including
        # nonrelational values. History remains append-only; stale values stay inert.
        current_sources = source_bindings(card, docs, items)
        nodes = dict(ledger_api.sourced(card))
        for item in items:
            history = ledger.get('entries', {}).get(ledger_api.key_of(item), [])
            current, eligible = _eligible(item, ledger, selected, card['id'], current_sources)
            view['entries'][ledger_api.key_of(item)] = [e for e in history if e not in current] + eligible
            if not eligible:
                raise ValueError('PROFILE_PROOF: no original selected proof of current complete value and passage')
            if eligible:
                worst = ledger_api.choose(eligible, ledger_api.not_before(card, nodes[item['pointer']]))
                record = next(r for r in records if ledger_api.key_of(r) == ledger_api.key_of(item))
                if record.get('checker') != worst['checker_binding']['checker']:
                    raise ValueError('PROFILE_PROOF: displayed checker differs from original frozen checker')
        passages = {ledger_api.key_of(x): x['source_passage'] for x in items}
        errors = ledger_api.check(card, view, passages, expected_items=items)
        if errors:
            result['errors'] = errors
            return result
        result.update(status='PASS', native_binding_valid=True, profile=copy.deepcopy(selected),
                      item_count=len(items), card_conditions=conditions, profile_contract=contract_identity())
    except (ValueError, KeyError, TypeError, OSError) as error:
        result['errors'] = [str(error)]
    return result


def stale_items(card, docs, selected, input_path, output_path):
    """A selected frozen pair is usable only for this exact current input."""
    items, _ = build(card, docs, selected)
    _items, meta, _request, _pins = io.load_input(input_path)
    # Merge adds integrity records and therefore changes the card content hash.
    # Read-only staleness compares the original pair and exact current items;
    # merge itself still requires the exact frozen pre-merge envelope.
    current = entailment.input_envelope(card)
    if any(meta['envelope'].get(key) != current.get(key) for key in
           ('card_id', 'card_version', 'proposition_version', 'converter_rules_sha256')):
        raise ValueError('PROFILE_PROOF: stale card/version/rules envelope')
    pair = io.load_pair(input_path, output_path, entailment.current_checker(), meta['envelope'])
    _profile_proof(pair.proof(), selected, card['id'])
    return [] if (pair.items == items and pair.proof()['input']['configuration']['source_bindings']
                  == source_bindings(card, docs, items)) else items


def carry(old_card, card, docs, selected, ledger):
    """Carry exact selected proofs; changed values remain NEEDS_CHECK, never PASS."""
    checks = card_checks(card, selected)
    if checks['errors']:
        raise ValueError('PROFILE_CARD: ' + '; '.join(checks['errors']))
    items, conditions = build(card, docs, selected)
    if old_card.get('id') != card.get('id') or ledger.get('card_id') != card.get('id'):
        raise ValueError('PROFILE_LEDGER: foreign carry card')
    if not _is_profile(ledger.get('renderer_profile')):
        raise ValueError('PROFILE_LEDGER: carry requires original selected history')
    records, rest = _selected_records(card, docs, selected, ledger, items)
    card['added']['integrity'] = {'entailment': records}
    _stamp(card, docs, selected, ledger, items, conditions)
    if rest:
        return {'status': 'NEEDS_CHECK', 'rest': rest, 'scientific_truth_evaluated': False}
    return validate_bundle(card, ledger, docs, selected)


def restore(card, docs, selected, ledger, archives):
    """Restore original fully validated card+ledger pairs, never card-only verdicts."""
    if not archives:
        raise ValueError('PROFILE_PROOF: restore requires original card and ledger pairs')
    if ledger.get('entries') and not _is_profile(ledger.get('renderer_profile')):
        raise ValueError('PROFILE_LEDGER: no legacy restore migration')
    checked = []
    for old_card, old_ledger in archives:
        if old_card.get('id') != card.get('id') or old_ledger.get('card_id') != card.get('id'):
            raise ValueError('PROFILE_PROOF: foreign archived pair')
        if validate_bundle(old_card, old_ledger, docs, selected)['status'] != 'PASS':
            raise ValueError('PROFILE_PROOF: archived selected pair does not validate')
        checked.append((old_card, old_ledger))
    # Validate all archives before appending; preserve original entries and proof bytes.
    for _, old_ledger in checked:
        for proof_id, proof in old_ledger.get('checker_io_proofs', {}).items():
            current = ledger.get('checker_io_proofs', {}).get(proof_id)
            if current is not None and current != proof:
                raise ValueError('PROFILE_PROOF: conflicting archived proof')
    for _, old_ledger in checked:
        for key, history in old_ledger['entries'].items():
            for entry in history:
                note = old_ledger['notes'].get(entry.get('note_sha256'))
                ledger_api.add_entry(ledger, key, copy.deepcopy(entry), note)
        ledger.setdefault('checker_io_proofs', {}).update(copy.deepcopy(old_ledger['checker_io_proofs']))
    ledger['renderer_profile'] = copy.deepcopy(selected)
    return carry(checked[0][0], card, docs, selected, ledger)


def export(card, ledger, docs, selected, path):
    result = validate_bundle(card, ledger, docs, selected)
    if result['status'] != 'PASS':
        raise ValueError('PROFILE export refused: ' + '; '.join(result['errors']))
    io.write_once(path, io.encoded(ledger))
    return result


def validate_files(card_path, ledger_path, selection_path, docs):
    """Deterministic in-process CI recipe; same sole entrypoint, no subprocess."""
    return validate_bundle(*(io.strict_json(io.read(p)) for p in (card_path, ledger_path)), docs,
                           io.strict_json(io.read(selection_path)))
