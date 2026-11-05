"""One invented schema-1.4 native-profile fixture; no real science or accounts."""
import json
import ohfkit

import checker_io as io
import native_entailment as entailment
import native_profile as profile
import projection_binding as projection
import native_ledger as check_ledger

from test_projection_adapter import Glyph


class ProfileFixture(Glyph):
    def __init__(self, root):
        # This fixture is not a reading and never inherits a real model identity.
        previous_model = ohfkit.MODEL
        ohfkit.MODEL = 'INVENTED_FAKE_ONLY_NOT_SCIENCE'
        try:
            super().__init__(root)
        finally:
            ohfkit.MODEL = previous_model
        card=self.card;card.pop('_author_names')
        card['author']['source']['kind']='synthetic_software_fixture'
        card['identity']['lifecycle']='fixture'
        card['added']['at']='2026-02-02T01:02:03Z'
        card['added']['source_verification']={'status':'not_refetchable',
            'reason':'Invented local fixture only; no article, source fetch or real scientific check.'}
        card['added']['by']['model']='INVENTED_FAKE_ONLY_NOT_SCIENCE'
        card['added']['by']['standard_release']={'version':'1.4.2',
            'commit':'bf1f582f977c2ac65e5537ebd9f1b1b19ae328d3'}
        # Invented unknown token totals, not observed runtime or production counters.
        card['added']['budget']['unknown_reasons'] = {
            'input_tokens': 'producer_runtime_does_not_expose',
            'output_tokens': 'producer_runtime_does_not_expose'}
        card['added']['layers']['profile']={'domain':['none']}
        card['added']['layers']['core']['atoms']=[{'id':'a_main',
            'statement':{'value':'Square precedes circle.','src':'p1'},
            'claim_type':{'value':'mechanism','src':'p1'},
            'modality':{'value':'proposed','src':'p1','basis_quote':self.doc.paragraphs[0]},
            'role':{'value':'core','src':'p1'}}]
        prediction=card['added']['layers']['predictions'][0]
        prediction.pop('intervention');prediction.pop('comparator')
        prediction['derives_from_atom_refs']={'value':['a_main'],'src':'p2'}
        self.line['target_ref']='pr_glyph'
        self.line['indirectness']['assessment']={'assessor':'Invented fixture author',
            'assessed_at':'2026-02-02T01:02:03Z','evidence_ref':{'kind':'artifact','sha256':self.doc.sha}}
        card['added'].pop('integrity')  # optional before the fake check; no fabricated placeholder verdict
        self.selected=profile.selection()
        self.rehash();self.ledger=check_ledger.new_ledger(card)

    def prepare_profile(self,name='check',verdict='entails'):
        self.rehash();inp=self.root/(name+'.json');out=self.root/(name+'-result.json')
        profile.freeze(self.card,self.docs,self.selected,inp,{'kind':'injected_fake','name':'invented-profile-checker',
            **getattr(self,'extra_configuration',{})})
        def fake(request,config):
            assert config['kind']=='injected_fake'
            actual=io.strict_json(request[len(entailment.PROMPT.read_bytes())+2:])
            results=[{'id':x['id'],'verdict':verdict,
                      **({'note':'Explicit invented fake verdict, not science.'} if verdict!='entails' else {})}
                     for x in actual]
            return {'request_sha256':projection.sha(request),
                    'configuration_sha256':projection.value_sha256(config),'result_bytes':io.encoded(results)}
        entailment.run_frozen_checker(inp,out,fake)
        return inp,out

    def merge_profile(self,name='check',verdict='entails'):
        inp,out=self.prepare_profile(name,verdict)
        profile.merge(self.card,self.docs,self.selected,inp,out,self.ledger)
        return inp,out

    def validate_profile(self):return profile.validate_bundle(self.card,self.ledger,self.docs,self.selected)
