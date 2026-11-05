"""A call record names its model, its materials and their licences — or is not written.

O1: every model call the kit makes gets a `call@1` record, in the accepted schema
`urn:hypothesis-arena:call:1`. The schema is carried in the kit (`references/call.schema.json`) so
the rules hash covers it; a copy whose bytes differ is refused rather than used.
"""
import json

import pytest

import callstore


def a_record(**over):
    kw = dict(role='extractor', card_id='h_example', version='2', stage='extraction',
              receipt={'id': 'checker25-rapa', 'sha256': 'a' * 64, 'kind': 'scrubbed-agent-evidence@1'}, model_requested='claude-opus-5', model_reported='claude-opus-5',
              effort='high', started_at='2026-10-23T14:00:00Z', finished_at='2026-10-23T14:00:42Z',
              prompt='Judge each item against its own passage.',
              instructions=[callstore.instruction('ENTAILMENT-PROMPT.md', b'Judge one value at a time.')],
              projections=[{'name': 'items.json', 'text': '[{"id": "r1"}]'}], materials=[],
              response_file=callstore.response('[{"id": "r1", "verdict": "entails"}]', False),
              final_message='18 items: 15 entails, 3 partial', status='completed',
              record_kind='synthetic_fixture',
              availability_notes=['synthetic_no_inference', 'usage_unavailable'])
    kw.update(over)
    return callstore.record(**kw)


def test_the_kit_carries_the_accepted_schema_and_refuses_other_bytes(tmp_path, monkeypatch):
    assert callstore.schema()['$id'] == callstore.SCHEMA_ID
    assert callstore.schema_bytes()
    other = tmp_path / 'call.schema.json'
    other.write_text('{"$id": "urn:hypothesis-arena:call:1"}')
    monkeypatch.setattr(callstore, 'SCHEMA_PATH', other)
    with pytest.raises(callstore.CallRecordError, match='not the accepted'):
        callstore.schema_bytes()


def test_a_record_of_a_kit_call_conforms():
    rec = a_record()
    assert callstore.validate(rec) == []
    assert set(rec['context']) == {'card_id', 'version', 'stage', 'receipt'}, 'the card branch, not the judge branch'


def test_an_open_licence_carries_its_identifier_and_may_carry_the_text():
    m = callstore.material('https://example.org/PMC1/fullTextXML', b'<article/>', 'CC-BY-4.0',
                           'XML .//permissions', text='<article/>')
    assert m['licence'] == {'status': 'open', 'identifier': 'CC-BY-4.0', 'evidence': 'XML .//permissions'}
    assert m['text'] == '<article/>'
    assert callstore.validate(a_record(materials=[m])) == []


def test_cc_by_3_is_named_now_and_an_unnamed_open_licence_still_stops_the_record():
    """The kit reported that it reads CC BY 3.0 — case 8's canonical snapshot is CC BY 3.0 Unported —
    and had no honest identifier for it; the schema's owners added exactly CC-BY-3.0 and CC-BY-2.5.
    A licence the list still does not name stops the record with the licence named, rather than being
    written as restricted or unknown: that would misstate a right and would forbid the text the
    licence permits. The mutant that mislabels it passes a record that lies."""
    m = callstore.material('https://web.archive.org/…id_/…', b'<html/>', 'CC-BY-3.0',
                           'the page footer, rel="license"')
    assert m['licence'] == {'status': 'open', 'identifier': 'CC-BY-3.0',
                            'evidence': 'the page footer, rel="license"'}
    for licence in callstore.OPEN_WITHOUT_IDENTIFIER:
        with pytest.raises(callstore.CallRecordError) as e:
            callstore.material('https://example.org/x', b'x', licence, 'somewhere')
        assert licence in str(e.value) and 'misstate' in str(e.value)


def test_a_restricted_material_is_logged_without_its_text():
    m = callstore.material('https://example.org/PMC2/fullTextXML', b'<article/>', 'CC-BY-NC-ND-4.0',
                           'XML .//permissions')
    assert m['licence']['status'] == 'restricted' and m['licence']['identifier'] is None
    assert 'text' not in m
    with pytest.raises(callstore.CallRecordError, match='may not be attached'):
        callstore.material('https://example.org/PMC2/fullTextXML', b'<article/>', 'CC-BY-NC-ND-4.0',
                           'XML .//permissions', text='<article/>')


def test_a_licence_without_a_locator_is_refused():
    with pytest.raises(callstore.CallRecordError, match='locator'):
        callstore.material('https://example.org/x', b'x', 'CC-BY-4.0', '')


def test_an_instruction_and_a_response_carry_their_own_hashes():
    i = callstore.instruction('references/entailment.md', b'A value is checked against its passage.')
    assert i['name'] == 'references/entailment.md' and len(i['sha256']) == 64 and i['text']
    r = callstore.response('[]', True)
    assert r['first_write_proven'] is True and len(r['sha256']) == 64
    assert callstore.validate(a_record(instructions=[i], response_file=r)) == []


def test_the_validator_catches_a_record_that_is_missing_a_member():
    rec = a_record()
    del rec['usage']
    assert any('usage' in e for e in callstore.validate(rec))
    bad = a_record(status='finished')  # not one of the schema's output states
    assert callstore.validate(bad), 'an output status outside the closed list must fail'


def test_a_note_outside_the_closed_list_is_refused():
    """availability_notes is ten fixed codes about missing evidence, not a field for prose. The kit
    makes calls the schema cannot name — a second reader, an entailment checker and the converter all
    fall under stage `extraction` — and that distinction stays in the kit's own store instead of being
    smuggled into a field that means something else."""
    with pytest.raises(callstore.CallRecordError, match='fixed codes'):
        a_record(availability_notes=['this call was the second reader of step 5'])
    assert callstore.validate(a_record(availability_notes=['usage_unavailable'])) == []


def test_the_stage_follows_the_role_and_a_judge_call_is_not_the_kit_s():
    """The schema ties the stage to the role: extractor means extraction, critic means critique. So
    the stage carries nothing the role does not, and the kit's three kinds of extraction call — the
    second reader, the entailment checker, the converter itself — are one role with one stage here.
    That distinction stays in the kit's own store; it is not smuggled into a field that means
    something else."""
    with pytest.raises(callstore.CallRecordError, match='ties the stage to the role'):
        a_record(stage='critique')
    with pytest.raises(callstore.CallRecordError, match='not one this kit writes'):
        a_record(role='judge')
    critic = a_record(role='critic', stage='critique')
    assert callstore.validate(critic) == []


@pytest.mark.parametrize('licence', ['CC-BY-1.0', 'CC-BY-2.0'])
def test_new_explicit_licence_ids_keep_their_exact_identity(licence):
    m = callstore.material('https://example.org/article', b'synthetic', licence,
                           'article/front/article-meta/permissions/license', text='synthetic')
    assert m['licence']['identifier'] == licence and m['licence']['status'] == 'open'
    assert m['text'] == 'synthetic'
    assert callstore.validate(a_record(materials=[m])) == []


@pytest.mark.parametrize('licence', ['CC BY', 'CC-BY', 'CC-BY-5.0',
                                    'CC-BY-NC-1.0', 'CC-BY-ND-2.0', 'CC-BY-SA-2.0'])
def test_schema_repin_does_not_open_unknown_or_restricted_material(licence):
    with pytest.raises(callstore.CallRecordError):
        callstore.material('https://example.org/article', b'synthetic', licence,
                           'article/front/article-meta/permissions/license', text='synthetic')
