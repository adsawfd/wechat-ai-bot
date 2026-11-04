import unittest
from unittest.mock import Mock
from group_identity_context import referenced_member_context
from respectful_contact import RespectfulContacts

class IdentityContextTests(unittest.TestCase):
    def setUp(self):
        self.db=Mock()
        self.db.get_group_members.return_value=[
            {'username':'me','nick_name':'微信助手'},
            {'username':'queen-id','nick_name':'SameNickname'},
            {'username':'other-id','nick_name':'ExampleMember'}]
        self.respect=RespectfulContacts(['queen-id'],{'queen-id':'尊重称呼'})
    def note(self,text,at=()):
        return referenced_member_context(self.db,'room@chatroom','me',text,at,self.respect)
    def test_text_at_unique_person_exposes_only_matching_title_no_private_id(self):
        note=self.note('@SameNickname 我@这个人是谁@微信助手',{'me'})
        self.assertIn('SameNickname',note)
        self.assertIn('尊重称呼',note)
        self.assertNotIn('queen-id',note)
        self.assertNotIn('ExampleMember',note)
    def test_native_id_survives_profile_nickname_change(self):
        self.db.get_group_members.return_value[1]['nick_name']='新昵称'
        note=self.note('@新昵称 这个人是谁',{'queen-id'})
        self.assertIn('新昵称',note)
        self.assertIn('尊重称呼',note)
        self.assertNotIn('SameNickname',note)
    def test_duplicate_or_partial_text_alias_not_bound_to_title(self):
        self.db.get_group_members.return_value.append({'username':'other','nick_name':'SameNickname'})
        note=self.note('@SameNickname 是谁')
        self.assertIn('重名',note)
        self.assertNotIn('尊重称呼',note)
        self.assertEqual(self.note('@SameNicknameabc 是谁'),'')
    def test_unmentioned_person_and_non_group_ignored(self):
        self.assertEqual(self.note('你叫什么'), '')
        self.assertEqual(referenced_member_context(self.db,'private','me','@SameNickname',(),self.respect),'')

if __name__ == '__main__': unittest.main()
