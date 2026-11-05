"""SubmittedText: a hypothesis submitted as text, with no publication behind it."""
import json

import pytest

import check_card
import entailment
import ohfkit
from conftest import invented_budget_counter

URL = 'urn:example:submission-1'
ANSWER = ('# A hypothesis\n\n'
          'Stiff aged matrix keeps lysosomes at the periphery. This could sustain mTORC1 in fibroblasts.\n\n'
          '  It can be tested by   culturing young cells on aged matrix.  \n\n\n'
          '1. **Matrix.** Old matrix is stiffer [link](https://example.org/a).\n')
MANIFEST = {'submitter': 'The owner of the project', 'basis': 'ran the model on their own subscription',
            'card_licence': 'CC-BY-4.0', 'author_kind': 'ai_system', 'system': 'A CLI', 'system_version': '0.1',
            'model': 'model-x', 'model_basis': 'cli configuration', 'reasoning_effort': 'medium',
            'reasoning_effort_basis': 'cli configuration', 'prompt_file': 'prompt.txt',
            'generated_at': '2026-10-21T11:54:10Z'}


def submitted(tmp_path, manifest=None, text=ANSWER, url=URL):
    (tmp_path / 'answer.md').write_text(text)
    (tmp_path / 'prompt.txt').write_text('Propose a testable hypothesis.\n')
    (tmp_path / 'answer.md.manifest.json').write_text(json.dumps(MANIFEST if manifest is None else manifest))
    (tmp_path / 'docs.json').write_text(json.dumps({url: {'kind': 'submitted', 'file': 'answer.md'}}))
    return ohfkit.SubmittedText(url, 'answer.md', tmp_path)


def test_paragraphs_are_split_on_blank_lines_and_the_hash_is_of_the_exact_bytes(tmp_path):
    doc = submitted(tmp_path)
    assert doc.paragraphs == ['# A hypothesis',
                              'Stiff aged matrix keeps lysosomes at the periphery. This could sustain mTORC1 in '
                              'fibroblasts.',
                              'It can be tested by culturing young cells on aged matrix.',
                              '1. **Matrix.** Old matrix is stiffer [link](https://example.org/a).']
    assert doc.sha == ohfkit.sha256(ANSWER.encode())
    assert doc.locator(2) == 'Submitted text paragraph 2 (1-based, paragraphs split on blank lines)'
    assert ohfkit.para_number(doc.locator(3)) == 3


def test_the_reading_time_is_kept_across_rebuilds(tmp_path):
    first = submitted(tmp_path).retrieved
    assert (tmp_path / 'answer.md.received').read_text() == first
    (tmp_path / 'answer.md.received').write_text('2026-10-21T12:00:01Z')
    assert submitted(tmp_path).retrieved == '2026-10-21T12:00:01Z'


def test_the_model_is_the_generator_beside_the_interface_with_its_basis_kept(tmp_path):
    doc = submitted(tmp_path)
    generator, generation, record = doc.generation()
    assert generator == {'kind': 'ai_system', 'system': 'A CLI', 'system_version': '0.1', 'model': 'model-x'}
    assert generation['run_id'] is None
    claims = json.loads(record['locator'].split('as stated: ', 1)[1])
    assert claims['model'] == 'model-x' and claims['model_basis'] == 'cli configuration'
    assert claims['reasoning_effort'] == 'medium' and claims['reasoning_effort_basis'] == 'cli configuration'
    assert claims['prompt_sha256'] == ohfkit.sha256(b'Propose a testable hypothesis.\n')


def test_a_model_seen_in_the_output_is_the_generator_with_that_basis(tmp_path):
    doc = submitted(tmp_path, dict(MANIFEST, model_basis=ohfkit.MODEL_OBSERVED))
    generator, _, record = doc.generation()
    assert generator['model'] == 'model-x'
    assert ohfkit.MODEL_OBSERVED in record['locator']


def test_a_generation_setting_is_carried_with_its_basis_and_is_not_a_generator_field(tmp_path):
    """A setting such as reasoning_effort is a configuration reference, not part of the generator:
    the schema fixes author.generator at kind, system, system_version and model."""
    doc = submitted(tmp_path, dict(MANIFEST, reasoning_effort='medium',
                                   reasoning_effort_basis='declared in the configuration, not visible in the output'))
    generator, _, record = doc.generation()
    assert set(generator) == {'kind', 'system', 'system_version', 'model'}
    claims = json.loads(record['locator'].split('as stated: ', 1)[1])
    assert claims['reasoning_effort'] == 'medium'
    assert claims['reasoning_effort_basis'] == 'declared in the configuration, not visible in the output'


def test_the_interface_is_the_system_and_does_not_take_the_model_s_place(tmp_path):
    """The interface the model was run through is `system`, beside the model, never instead of it."""
    doc = submitted(tmp_path, dict(MANIFEST, system='Codex CLI', system_version='0.163.0',
                                   model='gpt-6.1-sol', model_basis=ohfkit.MODEL_OBSERVED))
    generator = doc.generation()[0]
    assert generator['system'] == 'Codex CLI' and generator['system_version'] == '0.163.0'
    assert generator['model'] == 'gpt-6.1-sol'


def test_what_the_manifest_does_not_give_stays_unknown(tmp_path):
    m = {k: MANIFEST[k] for k in ohfkit.MANIFEST_REQUIRED}
    generator, generation, _ = submitted(tmp_path, m).generation()
    assert generator == {'kind': 'ai_system', 'system': None, 'system_version': None, 'model': None}
    assert set(generation.values()) == {None}


@pytest.mark.parametrize('change,error', [
    ({'card_licence': ''}, 'card_licence is required'),
    ({'author_kind': 'robot'}, 'author_kind is one of'),
    ({'modle': 'x'}, 'unknown members'),
    ({'model_basis': None}, 'model needs model_basis'),
    ({'reasoning_effort_basis': None}, 'reasoning_effort needs reasoning_effort_basis'),
])
def test_a_manifest_that_is_incomplete_or_misspelt_is_refused(tmp_path, change, error):
    m = {k: v for k, v in dict(MANIFEST, **change).items() if v is not None}
    with pytest.raises(ValueError, match=error):
        submitted(tmp_path, m)


def build(tmp_path, **manifest):
    doc = submitted(tmp_path, dict(MANIFEST, **manifest) if manifest else None)
    card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_sub', doc=doc, citation='An answer of a model to a prompt, 2026-10-21',
                           topic=['ageing'], sources={'p2': doc.src(2)}, author_names='unknown')
    card['author']['layers']['core']['statement'] = doc.author(
        2, 'Stiff aged matrix keeps lysosomes at the periphery.')
    out = tmp_path / 'card.json'
    ohfkit.finish(card, out)
    return json.loads(out.read_text()), doc


def test_the_skeleton_records_the_submitters_statement_not_a_licence(tmp_path):
    card, doc = build(tmp_path)
    src = card['author']['source']
    assert (src['kind'], src['rights_basis'], src['license'], src['url']) == (
        'submitted_text', ohfkit.SUBMITTED_BASIS, 'CC-BY-4.0', URL)
    assert src['source_text_sha256'] == doc.sha and 'doi' not in src
    assert card['facets']['source_class'] == 'submitted'
    assert card['author']['generator']['model'] == 'model-x'
    rights = card['added']['sources'][ohfkit.RIGHTS_KEY]
    assert doc.manifest_sha in rights['locator'] and '"submitter": "The owner of the project"' in rights['locator']
    assert ohfkit.GENERATION_KEY in card['added']['sources']


def test_check_card_reads_the_submitted_text_and_its_statement(tmp_path):
    card, _ = build(tmp_path)
    errors = check_card.conversion_errors(card, tmp_path)
    # Only the entailment pass is missing; the source, its statement and the quotation hold.
    assert len(errors) == 1 and errors[0].startswith('no entailment ledger')
    docs = entailment.docs_for(card, tmp_path)
    assert isinstance(docs[URL], ohfkit.SubmittedText)
    entailment.build(card, docs)


def test_a_changed_statement_after_the_build_fails_the_check(tmp_path):
    card, _ = build(tmp_path)
    (tmp_path / 'answer.md.manifest.json').write_text(json.dumps(dict(MANIFEST, card_licence='CC0-1.0')))
    errors = check_card.conversion_errors(card, tmp_path)
    assert any('licence of the main source' in e and 'submission manifest' in e for e in errors)


def test_a_quotation_must_be_in_its_paragraph(tmp_path):
    doc = submitted(tmp_path)
    with pytest.raises(ValueError):
        doc.author(2, 'Stiff young matrix keeps lysosomes at the periphery.')
    with pytest.raises(ValueError, match='is whole sentences'):
        doc.author_part(2, 'Stiff aged matrix keeps lysosomes at the periphery.', 'cut')


def test_a_url_that_disagrees_with_the_manifest_is_refused(tmp_path):
    with pytest.raises(ValueError, match='differs from the manifest url'):
        submitted(tmp_path, dict(MANIFEST, url='https://example.org/other'))


def test_without_a_url_the_submission_is_named_by_its_hash(tmp_path):
    (tmp_path / 'answer.md').write_text(ANSWER)
    (tmp_path / 'answer.md.manifest.json').write_text(json.dumps(MANIFEST))
    (tmp_path / 'prompt.txt').write_text('p')
    doc = ohfkit.SubmittedText(None, 'answer.md', tmp_path)
    assert doc.url == 'urn:sha256:' + doc.sha.split(':')[1]


RETOLD = ('We propose that stiff matrix keeps lysosomes at the periphery.\n\n'
          'Old matrix was stiffer in a 2024 study. It held under stretch. [*Effects of ageing*]'
          '(https://pmc.ncbi.nlm.nih.gov/articles/PMC11026642/).\n\n'
          'Soft substrates gather lysosomes near the nucleus (Wang et al., iScience, 2018).\n\n'
          'Lysosome position decides mTORC1 shutdown, PMID: 41559773.\n\n'
          'The prediction is ours: stiff matrix keeps mTORC1 on.\n')


def test_a_paragraph_that_carries_a_reference_is_a_third_party_candidate(tmp_path):
    doc = submitted(tmp_path, text=RETOLD)
    assert sorted(doc.third_party) == [2, 3, 4]
    kinds = {c['paragraph']: {r['kind'] for r in c['refs']} for c in doc.third_party_candidates()}
    assert kinds == {2: {'link', 'pmcid'}, 3: {'author_year'}, 4: {'pmid'}}
    # Every sentence of a paragraph that retells a work is refused, not only the one with the link.
    with pytest.raises(ohfkit.LicenceError, match='third_party_candidate'):
        doc.author(2, 'Old matrix was stiffer in a 2024 study.')
    with pytest.raises(ohfkit.LicenceError, match='third_party_candidate'):
        doc.author_part(3, 'Soft substrates gather lysosomes', 'cut')
    assert doc.author(5, 'The prediction is ours: stiff matrix keeps mTORC1 on.')['value']


def test_check_card_fails_an_author_value_in_a_third_party_paragraph(tmp_path):
    card, doc = build(tmp_path)
    # A builder that went around doc.author(): the value is in a paragraph that carries a link.
    card['author']['layers']['core']['statement'] = {
        'value': '1. **Matrix.** Old matrix is stiffer [link](https://example.org/a).', 'locator': doc.locator(4)}
    errors = check_card.conversion_errors(card, tmp_path)
    assert any('third_party_candidate' in e for e in errors)


def test_the_language_is_recorded_from_the_manifest_or_from_the_text(tmp_path):
    en = 'This is a hypothesis about ageing, and it links the matrix to the lysosome in the cell for a test.\n'
    assert submitted(tmp_path, text=en).language == 'en'
    assert submitted(tmp_path).language == 'und'          # too short to tell
    assert submitted(tmp_path, dict(MANIFEST, language='de')).language == 'de'
    ru = 'Это гипотеза о старении. Она связывает матрикс и лизосомы, и это можно проверить в опыте на клетках.\n'
    doc = submitted(tmp_path, text=ru * 2)
    assert doc.language == 'ru' and doc.language_basis.startswith('frequent words')
    assert submitted(tmp_path, text='mTORC1 S6K 4E-BP1.\n').language == 'und'
    card, _ = build(tmp_path)
    claims = json.loads(card['added']['sources'][ohfkit.GENERATION_KEY]['locator'].split('as stated: ', 1)[1])
    assert card['author']['source']['language'] == claims['language']['tag'] == 'und'


def test_a_marked_paragraph_is_a_hint_its_own_sentence_judged_own_may_be_quoted(tmp_path):
    text = ('Old matrix is stiffer [ref](https://example.org/a). We propose that this stiffness keeps mTORC1 on.\n\n'
            'An unmarked paragraph retells a study. Its result is the study\'s.\n')
    doc = submitted(tmp_path, text=text)
    with pytest.raises(ohfkit.LicenceError, match='not judged own'):
        doc.author(1, 'We propose that this stiffness keeps mTORC1 on.')
    d = doc.decide(1, 'We propose that this stiffness keeps mTORC1 on.', 'own', 'the proposal, in the first person')
    assert d['assessed_at'] and d['model'] == ohfkit.model() and d['assessor'].startswith('ohf-extractor')
    assert doc.author(1, 'We propose that this stiffness keeps mTORC1 on.')['value']
    doc.decide(1, 'Old matrix is stiffer [ref](https://example.org/a).', 'third_party', 'retells the linked study')
    with pytest.raises(ohfkit.LicenceError, match='judged third_party'):
        doc.author(1, 'Old matrix is stiffer [ref](https://example.org/a).')
    # The converter's judgement stands above the marking: an unmarked paragraph can be judged another's.
    doc.decide(2, "Its result is the study's.", 'third_party', 'a retelling with no reference')
    with pytest.raises(ohfkit.LicenceError, match='judged third_party'):
        doc.author(2, "Its result is the study's.")
    assert doc.author(2, 'An unmarked paragraph retells a study.')['value']
    report = doc.third_party_candidates()[0]['sentences']
    assert [(x['decision'], bool(x['reason'])) for x in report] == [('third_party', True), ('own', True)]


def test_a_decision_needs_a_sentence_of_the_paragraph_a_known_decision_and_a_reason(tmp_path):
    doc = submitted(tmp_path, text=RETOLD)
    with pytest.raises(ValueError, match='not one of its sentences'):
        doc.decide(2, 'Old matrix was stiffer', 'own', 'r')
    with pytest.raises(ValueError, match='decision is one of'):
        doc.decide(2, 'Old matrix was stiffer in a 2024 study.', 'mine', 'r')
    with pytest.raises(ValueError, match='needs its reason'):
        doc.decide(2, 'Old matrix was stiffer in a 2024 study.', 'own', ' ')


def build_judged(tmp_path):
    text = 'Old matrix is stiffer [ref](https://example.org/a). We propose that stiffness keeps mTORC1 on.\n'
    doc = submitted(tmp_path, text=text)
    doc.decide(1, 'We propose that stiffness keeps mTORC1 on.', 'own', 'the proposal')
    doc.decide(1, 'Old matrix is stiffer [ref](https://example.org/a).', 'third_party', 'retells the linked study')
    card = ohfkit.skeleton(budget_counter=invented_budget_counter, ident='h_sub', doc=doc, citation='An answer', topic=['ageing'],
                           sources={'p1': doc.src(1)}, author_names='unknown')
    card['author']['layers']['core']['statement'] = doc.author(1, 'We propose that stiffness keeps mTORC1 on.')
    card['added']['sources'][ohfkit.OWNERSHIP_KEY] = doc.ownership()
    out = tmp_path / 'card.json'
    ohfkit.finish(card, out)
    return json.loads(out.read_text()), doc


def test_check_card_reads_the_decisions_from_the_card(tmp_path):
    card, doc = build_judged(tmp_path)
    errors = check_card.conversion_errors(card, tmp_path)
    assert len(errors) == 1 and errors[0].startswith('no entailment ledger')
    # Without the record the value is an undecided sentence of a marked paragraph.
    bare = json.loads(json.dumps(card))
    del bare['added']['sources'][ohfkit.OWNERSHIP_KEY]
    assert any('not judged own' in e for e in check_card.conversion_errors(bare, tmp_path))
    # A decision turned to third_party after the build fails the value.
    turned = json.loads(json.dumps(card))
    decisions = ohfkit.decisions_in(turned)
    for d in decisions:
        d['decision'] = 'third_party'
    rec = turned['added']['sources'][ohfkit.OWNERSHIP_KEY]
    rec['locator'] = rec['locator'].split(ohfkit.OWNERSHIP_MARK)[0] + ohfkit.OWNERSHIP_MARK + json.dumps(decisions)
    assert any('judged third_party' in e for e in check_card.conversion_errors(turned, tmp_path))


def test_check_card_fails_a_decision_on_a_sentence_the_text_does_not_have(tmp_path):
    card, doc = build_judged(tmp_path)
    decisions = ohfkit.decisions_in(card) + [{'paragraph': 1, 'sentence': 'Invented.', 'decision': 'own',
                                              'reason': 'r', 'assessed_at': '2026-10-21T12:00:01Z'}]
    rec = card['added']['sources'][ohfkit.OWNERSHIP_KEY]
    rec['locator'] = rec['locator'].split(ohfkit.OWNERSHIP_MARK)[0] + ohfkit.OWNERSHIP_MARK + json.dumps(decisions)
    assert any("'Invented.' is not one of its sentences" in e for e in check_card.conversion_errors(card, tmp_path))


def test_markdown_emphasis_closes_a_sentence_in_a_submitted_text_only(tmp_path):
    para = '**Resistance is known in senescent cells.** So the new cause is the matrix. [ref](https://example.org/c).'
    doc = submitted(tmp_path, text=para + '\n')
    assert doc.sentences(1) == ['**Resistance is known in senescent cells.**', 'So the new cause is the matrix.',
                                '[ref](https://example.org/c).']
    doc.decide(1, 'So the new cause is the matrix.', 'own', 'the inference that follows from the cited finding')
    assert doc.author(1, 'So the new cause is the matrix.')['value']
    # An article keeps its sentence ends: the emphasis marks are not closers there.
    assert ohfkit.sentence_ends(para) != ohfkit.sentence_ends(para, ohfkit.MARKDOWN_CLOSERS)
    assert not ohfkit.whole_sentences(para, 'So the new cause is the matrix.')


def test_a_list_marker_needs_no_decision(tmp_path):
    para = '1. Old matrix is stiffer [ref](https://example.org/a). We propose that stiffness keeps mTORC1 on.'
    doc = submitted(tmp_path, text=para + '\n')
    assert doc.sentences(1)[0] == '1.'
    doc.decide(1, 'We propose that stiffness keeps mTORC1 on.', 'own', 'the proposal')
    doc.decide(1, 'Old matrix is stiffer [ref](https://example.org/a).', 'third_party', 'retells the linked study')
    assert ohfkit.owned(doc, doc.decisions, 1, 'We propose that stiffness keeps mTORC1 on.')
    # A value that spans the marker is still judged by the sentence after it.
    with pytest.raises(ohfkit.LicenceError, match='judged third_party'):
        ohfkit.owned(doc, doc.decisions, 1, '1. Old matrix is stiffer')
