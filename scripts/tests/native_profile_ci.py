"""Deterministic in-process CI scenario; one invented source, fake checker only.

The surrounding trusted CI verifies Git heads/trees before import. The pair
argument is a binding assertion, not an authentication mechanism in this helper.
"""
from pathlib import Path
import re

import checker_io as io
import native_profile as profile
import native_ledger as ledger_api
import projection_binding as projection
import ohfkit
from profile_fixture import ProfileFixture

PAIR_KEYS = {'extractor_commit', 'extractor_tree', 'standard_commit', 'standard_tree', 'rules_sha256'}


def run(output_directory, pair):
    if (type(pair) is not dict or pair.keys() != PAIR_KEYS
            or any(not isinstance(pair[key], str) or not re.fullmatch(r'[0-9a-f]{40}', pair[key])
                   for key in PAIR_KEYS - {'rules_sha256'})
            or pair['rules_sha256'] != ohfkit.rules_hash()):
        raise ValueError('CI_PAIR: exact trusted checkout/rules assertion required')
    root = Path(output_directory)
    if not root.is_dir() or root.is_symlink() or any(root.iterdir()):
        raise ValueError('CI_PAIR: provision one fresh local output directory')
    fixture = ProfileFixture(root)
    fixture.extra_configuration = {'ci_pair': dict(pair)}
    fixture.merge_profile()
    items, _ = profile.build(fixture.card, fixture.docs, fixture.selected)
    api = projection.reference()
    ordinary = api.value_items(fixture.card)
    if {(x['pointer'],x['basis']) for x in items} != {(x['pointer'],x['basis']) for x in ordinary}:
        raise ValueError('CI_PAIR: native and normative item rosters differ')
    bare_errors = api.check(fixture.card, fixture.ledger,
                           {ledger_api.key_of(x):x['source_passage'] for x in items})
    expected = ('direction', 'indirectness', 'sample_size', 'endpoint_kind')
    if len(bare_errors) != 4 or any(sum('/lines/0/'+key+'|' in e for e in bare_errors) != 1 for key in expected):
        raise ValueError('CI_PAIR: bare negative must contain exactly four labelled encoding mismatches')
    card, led, selector = root/'card.json', root/'ledger.json', root/'selector.json'
    io.write_once(card, io.encoded(fixture.card));io.write_once(selector, io.encoded(fixture.selected))
    profile.export(fixture.card, fixture.ledger, fixture.docs, fixture.selected, led)
    result = profile.validate_files(card, led, selector, fixture.docs)
    if result['status'] != 'PASS':
        raise ValueError('CI_PAIR: complete selected entrypoint refused: '+str(result['errors']))
    source = fixture.doc.profile_xml_bytes
    if projection.sha(source) != fixture.doc.sha:
        raise ValueError('CI_PAIR: invented source serialization differs')
    io.write_once(root/'source.xml', source)
    receipt = {'format':'ohf-native-profile-ci-result/1', 'status':'PASS_SYNTHETIC_NATIVE_PROFILE',
               'pair':dict(pair), 'pair_identity_source':'asserted by trusted CI after checkout verification',
               'normative_base':projection.STANDARD_COMMIT, 'validation':result,
               'bare_reader_status':'UNSUPPORTED_NATIVE_VALUES', 'bare_errors':bare_errors,
               'item_count':len(items), 'scientific_acceptance':False,
               'accounting_scope':'invented source and injected fake checker only; no model or HTTP',
               'model_calls':0, 'http_requests':0,
               'files':{p.name:projection.sha(io.read(p)) for p in (card,led,selector,root/'source.xml')}}
    io.write_once(root/'CI-RESULT.json', io.encoded(receipt))
    return receipt
