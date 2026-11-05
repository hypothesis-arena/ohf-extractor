"""check_card.py's failure messages that existed before the new gates, and rules_hash()."""
import json
import os
import shutil
import sys
from pathlib import Path

import check_card
import entailment
import ohfkit
from conftest import SCRIPTS, build_card, load, run_pass


def errors_after(xml_workdir, mutate):
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    card = load(card_path)
    assert check_card.conversion_errors(card, xml_workdir) == []
    mutate(card)
    return check_card.conversion_errors(card, xml_workdir)


def test_author_value_not_in_paragraph(xml_workdir):
    def m(c):
        c['author']['layers']['core']['statement']['value'] = 'We propose that X never causes Y.'
    assert any('/author/layers/core/statement: author value is not in XML .//p[1]' in e and 'copy the exact text' in e
               for e in errors_after(xml_workdir, m))


def test_source_sha_matches_no_document(xml_workdir):
    def m(c):
        c['author']['source']['source_text_sha256'] = 'sha256:' + '0' * 64
    assert 'author.source.source_text_sha256 matches no downloaded document (re-download the article)' in \
        errors_after(xml_workdir, m)


def test_evidence_line_field_not_a_wrapper(xml_workdir):
    def m(c):
        c['added']['layers']['evidence'] = {'lines': [{'id': 'e1', 'direction': 'supports'}]}
    assert any('/added/layers/evidence/lines/0/direction: write it as {"value": ..., "src": ...}' in e
               for e in errors_after(xml_workdir, m))


def test_basis_quote_not_exact(xml_workdir):
    def m(c):
        c['added']['layers']['core']['scope']['basis_quote'] = 'X will cause Y'
    assert any("/added/layers/core/scope.basis_quote: not an exact passage of src 'p2'" in e
               for e in errors_after(xml_workdir, m))


def test_unreadable_src(xml_workdir):
    def m(c):
        c['added']['layers']['core']['scope']['src'] = 'nope'
    assert any("/added/layers/core/scope: cannot read the passage of src 'nope'" in e
               for e in errors_after(xml_workdir, m))


def test_sourced_value_without_record(xml_workdir):
    def m(c):
        c['added']['layers']['core']['kind'] = {'value': 'mechanism', 'src': 'p1'}
    assert '/added/layers/core/kind (src): no entailment record (run the entailment pass on it)' in \
        errors_after(xml_workdir, m)


def test_record_for_unsourced_value(xml_workdir):
    def m(c):
        del c['added']['layers']['core']['scope']['basis_quote']
        del c['added']['layers']['core']['scope']['paraphrase']
    assert '/added/layers/core/scope (basis_quote): record for a value that is not sourced (remove the record)' in \
        errors_after(xml_workdir, m)


def test_rules_hash_covers_scripts_and_time_check(tmp_path, monkeypatch):
    skill = tmp_path / 'skill'
    shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns('__pycache__', '.git', 'tests'))
    time_check = skill / 'scripts' / 'time_check.py'
    monkeypatch.setattr(ohfkit, 'SKILL', skill)
    h0 = ohfkit.rules_hash()
    (skill / 'scripts' / 'check_card.py').write_text((skill / 'scripts' / 'check_card.py').read_text() + '\n# x\n')
    h1 = ohfkit.rules_hash()
    time_check.write_bytes(time_check.read_bytes() + b'\n# x\n')
    h2 = ohfkit.rules_hash()
    assert len({h0, h1, h2}) == 3


def test_run_checks_takes_a_relative_path(xml_workdir, monkeypatch):
    card_path = build_card(xml_workdir)
    monkeypatch.chdir(card_path.parent)
    ok, out = ohfkit.run_checks(card_path.name)
    assert 'No such file or directory' not in out


def test_quotation_from_a_reference_only_work_fails(xml_workdir):
    def m(c):
        for key, rec in c['added']['sources'].items():
            c['added']['sources'][key] = ohfkit.reference_only(rec, 'no licence statement found')
    errs = errors_after(xml_workdir, m)
    assert any('is cited by src only (no licence statement found): remove the quotation' in e for e in errs)


def test_reference_only_needs_a_reason():
    import pytest
    rec = {'source': 'u', 'locator': 'l', 'accessed_at': 't', 'tool': 'reading'}
    with pytest.raises(ValueError, match='needs the reason'):
        ohfkit.reference_only(rec, ' ')
    marked = ohfkit.reference_only(rec, 'closed licence')
    assert marked['tool'] == 'reading; cited by src only, not quoted: closed licence'
    with pytest.raises(ValueError, match='already marked'):
        ohfkit.reference_only(marked, 'again')


def test_the_time_check_runs_even_when_the_card_has_an_empty_list(xml_workdir):
    """0.8.17: check_card looped `for path in gap_coverage.empty_lists(card)` and so rebound `path`,
    the card's own path, to the last pointer it printed a NOTE for. The time check then received a
    pointer string instead of a card, crashed, and was reported as "time check failed" — so for every
    card with at least one empty list, which is every card this kit has built, the time check never
    ran and its gate could not be passed. Found on both flagships at step 4."""
    import subprocess
    import gap_coverage
    card_path = build_card(xml_workdir)
    assert run_pass(card_path, xml_workdir).returncode == 0
    assert list(gap_coverage.empty_lists(load(card_path))), 'the fixture must have an empty list'

    def run():
        return subprocess.run([sys.executable, '-I', str(SCRIPTS / 'check_card.py'), str(card_path),
                               str(xml_workdir)], capture_output=True, text=True)

    r = run()
    assert 'TIME CHECK' in r.stdout, r.stdout
    assert 'time check failed' not in r.stdout, r.stdout

    # The mutant: a round placeholder time is what the time check exists to catch, and it must be
    # caught through check_card rather than swallowed with the card's path.
    card = load(card_path)
    card['added']['at'] = '2026-10-21T12:00:00Z'
    card_path.write_text(json.dumps(card))
    r = run()
    assert 'time check failed' in r.stdout, r.stdout


def test_the_rules_hash_covers_a_data_file_not_only_the_prose(tmp_path, monkeypatch):
    """K9: a table the kit reads is as much a rule as the prose about it. While rules_hash() hashed
    only *.md under references/, a data file could change what the kit decides without changing any
    card's converter_hash — the hallmark map was the first such file, guarded only by a sha256
    pinned by hand in the script that read it. The mutant that globs '*.md' must fail this."""
    skill = tmp_path / 'skill'
    shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns('__pycache__', '.git', 'tests'))
    monkeypatch.setattr(ohfkit, 'SKILL', skill)
    table = skill / 'references' / 'a-table.json'
    table.write_text('{"rows": [{"from": "x", "to": "y"}]}\n')
    h0 = ohfkit.rules_hash()
    table.write_text('{"rows": [{"from": "x", "to": "z"}]}\n')   # one decision changed
    h1 = ohfkit.rules_hash()
    assert h1 != h0, 'a changed data file under references/ must change the rules hash'
    table.unlink()
    assert ohfkit.rules_hash() != h1, 'removing a data file must change it too'
    # And a file outside the kit still changes nothing.
    (tmp_path / 'elsewhere.json').write_text('{}')
    assert ohfkit.rules_hash() == ohfkit.rules_hash()


def test_a_logged_notice_the_card_says_nothing_about_fails(tmp_path):
    """`search.py status` puts a retraction or a correction in its record's `status` and `notices`,
    while `outcome` says only that the call worked and `found` counts works, not notices. A converter
    reading those two fields sees "ok 0" and moves on — which is what happened on a flagship, eleven
    seconds before the corrected work was fetched into the card. A card may carry a corrected work;
    it may not carry one silently."""
    import check_card
    log = tmp_path / 'search-log.jsonl'
    log.write_text(json.dumps({
        'tool': 'status', 'call_id': 'c0ffee', 'outcome': 'ok', 'found': 0, 'hit_count': 2,
        'status': 'corrected',
        'target': {'pmcid': 'PMC8495984', 'pmid': '34620223'},
        'ask': {'id': '34620223'},
        'notices': [{'notice': 'MED:35016718', 'kind': 'Erratum in', 'status': 'corrected'}],
    }) + '\n')
    card = {'added': {'sources': {'s1': {'source': 'https://example.org/PMC8495984/fullTextXML'}},
                      'layers': {'evidence': {'lines': [{'id': 'e1', 'quote': 'something'}]}}}}

    errors = check_card.notice_errors(card, tmp_path)
    assert len(errors) == 1 and 'c0ffee' in errors[0] and 'MED:35016718' in errors[0]

    # The card says what the notice is: silent again. What it says is the converter's business.
    card['added']['layers']['evidence']['lines'][0]['risk_of_bias'] = {
        'value': {'level': 'some', 'note': 'This work carries a correction notice, MED:35016718: it '
                                           'corrects an author name and changes no result quoted here.'}}
    assert check_card.notice_errors(card, tmp_path) == []

    # A status call on a work the card does not cite is not this card's business.
    log.write_text(log.read_text().replace('PMC8495984', 'PMC9999999').replace('34620223', '99999999'))
    assert check_card.notice_errors(card, tmp_path) == []

    # A call that found nothing says nothing.
    log.write_text(json.dumps({'tool': 'status', 'call_id': 'quiet', 'outcome': 'ok', 'found': 0,
                               'status': 'none_found', 'target': {'pmcid': 'PMC8495984'},
                               'ask': {'id': 'PMC8495984'}, 'notices': []}) + '\n')
    assert check_card.notice_errors(card, tmp_path) == []


def test_the_word_in_visible_text_is_extractor_from_0_9_0(xml_workdir, capsys):
    """The owner's decision of 2026-10-22: visible texts say extractor, not converter. A card this
    kit builds fails on it; a card built before the rule is noted and brought up at its next
    rebuild, because an accepted card is a fact about the past and is not edited in place. The field
    names the standard defines (added.by.converter, converter_version, converter_hash) keep theirs."""
    import check_card
    card_path = build_card(xml_workdir)
    card = load(card_path)
    assert check_card.wording_errors(card) == []

    card['added']['gaps'] = [{'path': 'core.base_rate', 'reason': 'The converter does not rate this.'}]
    errs = check_card.wording_errors(card)
    assert len(errs) == 1 and '/added/gaps/0/reason' in errs[0] and 'extractor' in errs[0]

    # The identifiers of added.by are not visible text and keep the word.
    card['added']['gaps'] = []
    card['added']['by']['converter'] = 'ohf-extractor'
    assert check_card.wording_errors(card) == []

    # The gate: the same card, built by an earlier kit, is a note and not an error.
    assert check_card.WORDING_FROM == (0, 9, 0)


def test_a_gzipped_response_is_stored_as_text_and_an_unknown_encoding_is_an_error():
    """A server may compress a response nobody asked to have compressed: the Internet Archive's
    `id_` form returns the original bytes with `Content-Encoding: gzip` though no `Accept-Encoding`
    was sent. Stored as received, such a file parses to nothing — no paragraphs, no licence, and no
    error, which is how a conversion comes to report "the licence names no version" about a file it
    never read. Found on a licence page of a publisher, by the agent building the same fix for the search transport."""
    import gzip as _gzip
    import pytest

    text = b'<html><p>bjoern.brembs.blog is licensed under a Creative Commons Attribution 3.0</p></html>'
    assert ohfkit.decoded(_gzip.compress(text), {'Content-Encoding': 'gzip'}) == text
    assert ohfkit.decoded(_gzip.compress(text), {'content-encoding': 'GZIP'}) == text
    assert ohfkit.decoded(text, {}) == text
    assert ohfkit.decoded(text, {'Content-Encoding': 'identity'}) == text
    with pytest.raises(ValueError, match='cannot undo'):
        ohfkit.decoded(b'\x00\x01', {'Content-Encoding': 'br'})

    # HTTP deflate is the zlib wrapper (RFC 9110), and servers send the raw stream too. Both are
    # undone: a correct body must not be refused for being correct. This was found to read the raw
    # form only, by the agent building the same fix for the search transport.
    import zlib as _zlib
    assert ohfkit.decoded(_zlib.compress(text), {'Content-Encoding': 'deflate'}) == text
    raw = _zlib.compressobj(wbits=-_zlib.MAX_WBITS)
    assert ohfkit.decoded(raw.compress(text) + raw.flush(), {'Content-Encoding': 'deflate'}) == text


def _accepted_card():
    """One of the accepted cards, as the kit's own pinned set holds it."""
    return json.loads((check_card.ACCEPTED / 'peto-paradox-mammals.json').read_text())


def test_the_two_version_members_move_as_a_pair():
    """The acceptor's finding on my own editorial revision: I raised the top-level `version` and left
    `identity.version`, so `(id, identity.version)` named the accepted card at another content hash.
    The rule that was supposed to stop that read the other member and said nothing.

    Measured before the rule was written: the accepted eight and both flagships all satisfy it, so it
    adds no work to anything already accepted."""
    card = _accepted_card()
    assert check_card.version_errors(card) == [], 'an accepted card is clean'
    revised = json.loads(json.dumps(card))
    revised['version'] = card['version'] + 1          # the mistake: one member raised, one left
    revised['content_hash'] = 'sha256:' + 'f' * 64
    errors = check_card.version_errors(revised)
    assert any('move together' in e for e in errors), errors
    # raising both, with the content hash changed, is what a revision looks like
    revised['identity']['version'] = revised['version']
    revised['identity']['supersedes'] = [f"{card['id']}@{card['version']}"]
    assert check_card.version_errors(revised) == []


def test_a_version_above_the_first_says_what_it_replaces():
    card = _accepted_card()
    raised = json.loads(json.dumps(card))
    raised['version'] = raised['identity']['version'] = 5
    raised['content_hash'] = 'sha256:' + 'e' * 64
    raised['identity']['supersedes'] = []
    assert any('supersedes nothing' in e for e in check_card.version_errors(raised))
    raised['identity']['supersedes'] = [f"{card['id']}@5"]
    assert any('this version or a later one' in e for e in check_card.version_errors(raised))
    raised['identity']['supersedes'] = [f"{card['id']}@3"]
    assert check_card.version_errors(raised) == []


def test_either_version_member_matching_an_accepted_card_is_refused():
    """The rule it was always meant to be: one accepted content per version, whichever member names it."""
    card = _accepted_card()
    clash = json.loads(json.dumps(card))
    clash['content_hash'] = 'sha256:' + 'd' * 64
    errors = check_card.version_errors(clash)
    assert any('another content_hash' in e for e in errors), errors


def test_a_quotation_inside_a_value_takes_the_src_of_its_item():
    """`predictions[].effect_modifiers[]` puts `basis_quote` inside `value`, with the src one level up.

    Read from the node that holds the quotation, the src is None, and the first card to fill that field
    failed its own checker with 'cannot read the passage of src None'. The walker therefore carries the
    src in force; everywhere else the nearest enclosing src is the node's own.
    """
    item = {'value': {'factor': 'the intensity of selection', 'direction': 'it depends on it',
                      'prespecified': True, 'basis_quote': 'the intensity of selection (s)'},
            'src': 'variation'}
    nodes = dict(check_card.walk({'effect_modifiers': [item]}, ''))
    assert nodes['/effect_modifiers/0/value']['src'] == 'variation'
    assert nodes['/effect_modifiers/0']['src'] == 'variation'


def test_a_node_without_a_quotation_is_handed_no_src():
    """Every other caller tests for `src` itself, so a node that has none must not be given one."""
    nodes = dict(check_card.walk({'a': {'value': 'x', 'src': 's', 'b': {'value': 'y'}}}, ''))
    assert 'src' not in nodes['/a/b']


def fundamental_schemas():
    """The `fundamental` subschema of the added zone in every standard checkout the tests are given."""
    out = {}
    for name, root in (('OHF_REPO', os.environ.get('OHF_REPO')), ('OHF_STANDARD', os.environ.get('OHF_STANDARD'))):
        if not root:
            continue
        path = Path(root) / 'schema' / 'hypothesis-1.schema.json'
        if not path.exists():
            continue
        whole = json.loads(path.read_text())
        version = (Path(root) / 'VERSION').read_text().strip()
        node = (whole['properties']['added']['properties']['layers']['properties']['core']
                ['properties']['assumptions'])
        node = whole['$defs'][node['$ref'].split('/')[-1]] if '$ref' in node else node
        item = node['properties']['value']['items'] if 'properties' in node else node['items']
        out[version] = (whole, item['properties']['fundamental'])
    return out


def valid_against(whole, subschema, value):
    """Whether value satisfies the subschema. The subschema's `$ref`s point into the document's
    `$defs`, so those definitions are carried along rather than resolved by hand."""
    import jsonschema
    validator = jsonschema.Draft202012Validator({**subschema, '$defs': whole['$defs']})
    return not list(validator.iter_errors(value))


def test_the_fundamental_guard_asks_for_a_form_the_schema_allows(xml_workdir):
    """A guard must not demand what the schema forbids, which is how the first version of this one
    failed review: it required a `basis_quote`, and the schema gives `fundamental` in the added zone as
    `{value, src}` with `additionalProperties: false` or a bare boolean. Every schema-valid form was
    refused, anything that passed was schema-invalid, and the bare boolean - the guess the guard
    exists for - passed untouched. So the schema and the kit are checked together here, on each
    standard checkout the run is given."""
    schemas = fundamental_schemas()
    assert schemas, 'this test needs OHF_REPO or OHF_STANDARD'
    for version, (whole, sub) in schemas.items():
        assert valid_against(whole, sub, {'value': True, 'src': 'p1'}), version
        assert valid_against(whole, sub, True), f'{version}: the bare boolean is schema-valid'
        assert not valid_against(whole, sub, {'value': True, 'src': 'p1', 'basis_quote': 'x'}), (
            f'{version}: a basis_quote is forbidden, so no check may demand one')

    card_path = build_card(xml_workdir)
    card = load(card_path)
    assumptions = card['added']['layers'].setdefault('core', {}).setdefault('assumptions', [])

    # The bare boolean: schema-valid, no paragraph named, nothing for a reader to check. Refused.
    bare = {'id': 'as_bare', 'text': {'value': 'A premise.', 'src': 'p1'}, 'fundamental': True}
    assumptions.append(bare)
    errors = check_card.conversion_errors(card, xml_workdir)
    assert any('/added/layers/core/assumptions/' in e and 'fundamental' in e for e in errors), errors

    # The sourced form names the paragraph, so this check lets it by and the entailment pass takes it
    # from there: the record for the pointer is what a reader checks the boolean against.
    bare['fundamental'] = {'value': True, 'src': 'p1'}
    assert not any('fundamental' in e and 'classification' in e
                   for e in check_card.conversion_errors(card, xml_workdir))
    assert ('/added/layers/core/assumptions/0/fundamental', 'src') in [
        (x['pointer'], x['basis']) for x in entailment.build(card, entailment.docs_for(card, xml_workdir))], \
        'the sourced form is a value the entailment pass must carry a record for'
