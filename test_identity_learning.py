import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from group_profiles import GroupProfiles
from identity_learning import IdentityMemory


class IdentityLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'identity.sqlite3'
        self.now=0
        self.store=IdentityMemory('me',{'boss'},self.path,clock=lambda:self.now)
        self.members=[{'username':'me','nick_name':'微信助手'}, {'username':'target','nick_name':'：)'},
                      {'username':'boss','nick_name':'🐾'}, {'username':'other','nick_name':'成员乙'}]
        self.profiles=GroupProfiles('group@chatroom',[{'member_id':'other','group_nickname':'成员乙','real_name':'示例甲'}])
        self.client=Mock();self.client.with_options.return_value=self.client
    def tearDown(self): self.temp.cleanup()
    def classify(self,**data):
        payload={'action':'remember','subject':'这个人','name':'ExampleName','confidence':.98,**data}
        self.client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    def teach(self,text='@：) @微信助手 我@这个人是ExampleName，记住了',at=('me','target'),sender='boss'):
        return self.store.teach(self.client,'model','group@chatroom',sender,text,set(at),self.members,self.profiles,'me')
    def question(self,text,at=(),scope='group@chatroom'):
        return self.store.question(scope,text,set(at),self.members,'me',self.profiles)
    def test_real_at_binds_account_and_questions_work_both_directions_after_restart(self):
        self.classify()
        self.assertEqual(self.teach()['message'],'记住了：这个人是ExampleName。')
        self.store=IdentityMemory('me',{'boss'},self.path,clock=lambda:self.now)
        self.assertEqual(self.question('@：) 这个人是谁',('target',)),(True,'target','ExampleName'))
        self.assertEqual(self.question('ExampleName是谁'),(True,'target','ExampleName'))
        self.members[1]['nick_name']='新名字'
        self.assertEqual(self.question('新名字是谁'),(True,'target','ExampleName'))
        self.assertEqual(self.question('ExampleName是谁',scope='other@chatroom'),(False,None,None))
        self.assertEqual(IdentityMemory('other',{'boss'},self.path).facts('group@chatroom'),{})
    def test_text_subject_unique_can_be_learned_without_native_at(self):
        self.classify(subject='成员乙',name='笑笑')
        result=self.teach('成员乙是笑笑，记住了',at=('me',))
        self.assertEqual(result['status'],'saved')
        self.assertEqual(self.question('笑笑是谁'),(True,'other','笑笑'))
    def test_untrusted_ambiguous_and_nonverbatim_not_stored(self):
        self.classify()
        self.assertIsNone(self.teach(sender='other'))
        self.client.with_options.assert_not_called()
        self.assertEqual(self.teach(at=('me','target','other'))['status'],'unconfirmed')
        self.classify(name='猜测的名字')
        self.assertEqual(self.teach()['status'],'unconfirmed')
        self.assertFalse(self.store.facts('group@chatroom'))
    def test_mismatched_at_subject_or_model_failure_cannot_claim_success(self):
        self.classify(subject='成员乙',name='ExampleName')
        self.assertEqual(self.teach()['status'],'unconfirmed')
        self.client.chat.completions.create.side_effect=RuntimeError('unavailable')
        self.assertEqual(self.teach()['status'],'unconfirmed')
        self.assertFalse(self.store.facts('group@chatroom'))
    def test_new_explicit_teaching_updates_only_the_target_in_this_group(self):
        self.classify()
        self.teach()
        self.classify(name='新名字')
        self.teach('@：) @微信助手 这个人是新名字，记住了')
        self.assertEqual(self.question('新名字是谁'),(True,'target','新名字'))
        self.assertEqual(self.question('ExampleName是谁'),(False,None,None))
    def test_model_can_refer_to_the_native_target_as_i_at_this_person(self):
        self.classify(subject='我@这个人')
        self.assertEqual(self.teach()['status'],'saved')
    def test_anonymous_name_collisions_are_not_guessed(self):
        self.store.store('group@chatroom','target','ExampleName')
        self.store.store('group@chatroom','other','ExampleName')
        self.assertEqual(self.question('ExampleName是谁'),(True,None,None))
        self.assertEqual(self.question('@：)是谁',('target',)),(True,'target','ExampleName'))
    def test_pending_question_only_same_sender_room_and_short_call(self):
        self.store.store('group@chatroom','target','ExampleName')
        self.store.remember_pending('group@chatroom','boss','@：) 这个人是谁',{'target'},self.members,'me',self.profiles)
        args=('group@chatroom','boss','@微信助手',{'me'},self.members,'me',['微信助手'])
        self.assertEqual(self.store.take_pending('group@chatroom','other','@微信助手',{'me'},self.members,'me',['微信助手']),(False,None,None))
        self.assertEqual(self.store.take_pending(*args),(True,'target','ExampleName'))
        self.assertEqual(self.store.take_pending(*args),(False,None,None))
        self.store.remember_pending('group@chatroom','boss','@：) 这个人是谁',{'target'},self.members,'me',self.profiles)
        self.now=121
        self.assertEqual(self.store.take_pending(*args),(False,None,None))

if __name__=='__main__': unittest.main()
