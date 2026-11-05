#!/usr/bin/env python3
"""Every model call the kit makes, written as a `call@1` record (O1).

Why the kit writes these at all: a card's verdicts come from model calls, and a verdict whose call
cannot be read again is a claim with nothing behind it. The ledger already holds what was decided;
this holds **who was asked, with what, and what came back** — the model and the reasoning effort as
the harness reported them, the prompt and instructions, each material with its licence, the output,
and the timing.

The kit carries exact accepted call@1 schema ce44, including explicitly versioned CC BY 1.0,
2.0, 2.5, 3.0 and 4.0 identifiers. Source admission remains the extractor's own policy; naming a
material licence in a record does not grant admission. Unversioned and unknown licences are not
mapped to an open identifier. The pinned bytes are verified before a record is checked.

Usage:
  callstore.py validate RECORD.json          (check one record against the pinned schema)
  callstore.py schema-sha256                 (the sha256 of the schema this kit carries)
"""
import hashlib
import json
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'references' / 'call.schema.json'
SCHEMA_SHA256 = 'sha256:ce44a47451e4cf7cd1d938780d24b4448b911ad6bc912826befddf9ae384fc80'
SCHEMA_ID = 'urn:hypothesis-arena:call:1'   # the $id of the schema file
SCHEMA_CONST = 'call@1'                     # the value the record's own `schema` member carries

# The identifiers the schema allows beside `status: open`, and what the kit's own licence strings map
# to. A kit licence with no entry here has no honest identifier and stops the record.
OPEN_IDENTIFIERS = {
    'CC0-1.0': 'CC0-1.0',
    'CC-BY-4.0': 'CC-BY-4.0',
    'CC-BY-3.0': 'CC-BY-3.0',
    'CC-BY-2.5': 'CC-BY-2.5',
    'CC-BY-2.0': 'CC-BY-2.0',
    'CC-BY-1.0': 'CC-BY-1.0',
    'public-domain': 'SOURCE-PUBLIC-DOMAIN',
}
# Reserved for a future admitted licence whose identifier is not yet in the pinned schema.
OPEN_WITHOUT_IDENTIFIER = ()

class CallRecordError(ValueError):
    """The record cannot be written as it stands."""


def schema_bytes():
    """The pinned schema's bytes, refusing a copy that is not the accepted ones."""
    raw = SCHEMA_PATH.read_bytes()
    got = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if got != SCHEMA_SHA256:
        raise CallRecordError(f'{SCHEMA_PATH.name} is {got}, not the accepted {SCHEMA_SHA256}: '
                              f'a record written against other bytes names a schema it was not checked by')
    return raw


def schema():
    return json.loads(schema_bytes())


def licence_of_material(kit_licence, evidence):
    """The schema's licence object for a material the kit read, or a refusal.

    `kit_licence` is what `ohfkit.licence_of` returned for the source; `evidence` says where the
    licence was read (a locator, not a judgement). A licence the kit accepts but the schema's open
    list does not name stops the record here, with the licence named.
    """
    if not evidence:
        raise CallRecordError('a material\'s licence needs the locator it was read from, not a bare claim')
    if kit_licence in OPEN_IDENTIFIERS:
        return {'status': 'open', 'identifier': OPEN_IDENTIFIERS[kit_licence], 'evidence': evidence}
    if kit_licence in OPEN_WITHOUT_IDENTIFIER:
        raise CallRecordError(
            f'{kit_licence} is open and the kit reads it, but the schema\'s closed list of open '
            f'identifiers does not name it ({", ".join(sorted(OPEN_IDENTIFIERS))}). Writing it as '
            f'restricted or unknown would misstate the licence, and would forbid the text it permits: '
            f'no record for this material until the list is extended by its owners')
    return {'status': 'restricted', 'identifier': None, 'evidence': evidence}


def material(ref, data, kit_licence, evidence, text=None):
    """One material of a call: its address, the sha256 of the bytes read, its licence, and its text
    only where the licence is open."""
    out = {'ref': ref, 'sha256': hashlib.sha256(data).hexdigest(),
           'licence': licence_of_material(kit_licence, evidence)}
    if text is not None:
        if out['licence']['status'] != 'open':
            raise CallRecordError(f'{ref}: the text may not be attached under a licence that is not open')
        out['text'] = text
    return out


# The schema's stages for a card call. There are two, and the kit makes more kinds of call than
# that: the second reader of step 5, the entailment checker of step 6 and the converter itself all
# fall under `extraction`; only the critics of step 7 are `critique`.
#
# **There is nowhere in the record to say which of them a call was.** `availability_notes` is a
# closed list of ten codes about missing evidence, not a field for prose, and the kit will not
# smuggle a step into a field that means something else. So a `call@1` record cannot today tell a
# second reader that never saw the card from a checker that did not convert it — which is precisely
# the independence the store exists to show. Reported to the schema's owners; until a finer stage or
# a step member exists, the kit's own `CALLS.json` keeps that distinction and the records do not
# claim it.
# The schema ties the stage to the role: an extractor's call is `extraction`, a critic's is
# `critique`. So the stage carries nothing the role does not, and the kit's three kinds of
# extraction call — the second reader, the entailment checker, the converter itself — are one
# role with one stage in this record.
STAGE_OF_ROLE = {'extractor': 'extraction', 'critic': 'critique'}
# The ten codes of availability_notes, as the schema fixes them. A note the kit wants to make that
# is not one of these belongs in the kit's own store, not here.
AVAILABILITY_NOTES = ('usage_unavailable', 'synthetic_no_inference', 'material_text_withheld_licence',
                      'reported_model_unavailable', 'response_file_unavailable',
                      'final_message_unavailable', 'session_log_unavailable',
                      'checker_output_unavailable', 'first_response_unproven',
                      'interrupted_before_response')


def instruction(name, data):
    """One instruction file of a call: its name, the sha256 of its bytes, and its text. The kit's
    instructions are its own files (SKILL.md, references/*.md, a prompt), so the text is always
    carried and the hash is of the bytes the call actually used."""
    text = data.decode('utf-8') if isinstance(data, bytes) else data
    return {'name': name, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'text': text}


def response(text, first_write_proven):
    """The response file of a call: its text, its sha256 and whether the first write was proven.

    `first_write_proven` is false unless the harness showed the file was written once and not
    rewritten; a record that cannot show it carries the note `first_response_unproven`.
    """
    return {'text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'first_write_proven': bool(first_write_proven)}


def record(*, role, card_id, version, stage, receipt, model_requested, model_reported, effort,
           started_at, finished_at, prompt, instructions, projections, materials, response_file,
           final_message, status, usage=None, session_events=(), stdout='', stderr='',
           checker_output='', representation=None, availability_notes=(), redaction=None,
           record_kind='model_call'):
    """A `call@1` record for a call the kit made about one card.

    The context branch is the one for a card: `card_id`, `version`, `stage`, `receipt` — a judge's
    branch (two cards and a question) is not this kit's to write. `version` is a string in the
    schema, so a card's integer version is written as one. `receipt` is an object naming a scrubbed
    evidence file (`kind: scrubbed-agent-evidence@1`), which means a **real** record cannot be
    written before the scrubber exists: an agent transcript carries machine paths, session ids and
    host names. Until then only `record_kind: synthetic_fixture` records are produced, and they say
    so.
    """
    for note in availability_notes:
        if note not in AVAILABILITY_NOTES:
            raise CallRecordError(f'availability_notes takes one of {len(AVAILABILITY_NOTES)} fixed codes, '
                                  f'not {note!r}: what the kit wants to say about a call that the schema '
                                  f'has no member for stays in the kit\'s own store')
    expected = STAGE_OF_ROLE.get(role)
    if expected is None:
        raise CallRecordError(f'role {role!r} is not one this kit writes ({", ".join(STAGE_OF_ROLE)}); '
                              f'a judge\'s call is not the kit\'s to record')
    if stage != expected:
        raise CallRecordError(f'the schema ties the stage to the role: {role!r} means {expected!r}, '
                              f'not {stage!r}')
    return {
        'schema': SCHEMA_CONST,
        'record_kind': record_kind,
        'role': role,
        'context': {'card_id': card_id, 'version': str(version), 'stage': stage, 'receipt': receipt},
        'model': {'requested': model_requested, 'reported': model_reported},
        'effort': effort,
        'timing': {'started_at': started_at, 'finished_at': finished_at},
        'usage': usage,
        'input': {'prompt': prompt, 'instructions': list(instructions),
                  'projections': list(projections), 'materials': list(materials)},
        'output': {'response_file': response_file, 'final_message': final_message, 'status': status},
        'evidence': {'session_events': list(session_events), 'stdout': stdout, 'stderr': stderr,
                     'checker_output': checker_output,
                     'representation': representation or 'scrubbed-copy-not-source-bytes'},
        'availability_notes': list(availability_notes),
        'redaction': redaction or {'state': 'synthetic_no_secrets' if record_kind == 'synthetic_fixture'
                                   else 'scrubbed', 'policy_sha256': '0' * 64},
    }


def validate(rec):
    """Errors against the pinned schema, as strings; empty when the record conforms."""
    import jsonschema
    validator = jsonschema.Draft202012Validator(schema())
    return [f'{"/".join(str(p) for p in e.absolute_path) or "(root)"}: {e.message}'
            for e in sorted(validator.iter_errors(rec), key=lambda e: list(e.absolute_path))]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == 'schema-sha256':
        print(SCHEMA_SHA256)
        schema_bytes()
        return
    if sys.argv[1] == 'validate' and len(sys.argv) == 3:
        errors = validate(json.loads(Path(sys.argv[2]).read_text()))
        for e in errors:
            print('FAIL', e)
        print('CALL RECORD', 'FAIL' if errors else 'PASS', len(errors))
        sys.exit(1 if errors else 0)
    sys.exit(__doc__)


if __name__ == '__main__':
    main()
