import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from group_profiles import GroupProfiles
from mention_planner import build_mention_roster

class GroupProfilesTests(unittest.TestCase):
    def setUp(self):
        self.people=[{'member_id':'queen','group_nickname':'成员乙','real_name':'示例甲','title':'尊重称呼'},
                     {'member_id':'other','group_nickname':'SameNickname','real_name':'示例乙','title':''},
                     {'member_id':'lele','group_nickname':'群昵称甲','real_name':'示例丁','title':'友好称呼'}]
        self.profiles=GroupProfiles('group@chatroom',self.people)
        self.members=[{'username':'me','nick_name':'微信助手'},
                      {'username':'queen','nick_name':'SameNickname'},
                      {'username':'other','nick_name':'ExampleMember'},
                      {'username':'lele','nick_name':'MemberD'}]
    def context(self,text,ids=(),sender='other'):
        return self.profiles.context('group@chatroom',sender,text,ids,self.members,'me')
    def test_user_bound_group_and_wechat_nicknames_are_distinct(self):
        info=json.loads(self.context('SameNickname是谁',sender='caller').split('\n')[-1])
        self.assertEqual({p['用户提供的姓名'] for p in info},{'示例甲','示例乙'})
        self.assertNotIn('queen',str(info))
        self.assertNotIn('other',str(info))
        info=json.loads(self.context('@SameNickname 是谁',ids={'me','other'},sender='caller').split('\n')[-1])
        self.assertEqual([p['用户提供的姓名'] for p in info],['示例乙'])
        self.assertTrue(info[0]['本次原生at'])
    def test_latest_profile_name_and_titles_are_scoped_to_actual_id(self):
        self.members[3]['nick_name']='新的昵称'
        info=json.loads(self.context('你好',sender='lele').split('\n')[-1])
        self.assertEqual(info[0]['当前微信资料昵称'],'新的昵称')
        self.assertEqual(self.profiles.address('group@chatroom','lele','早上好'),'友好称呼，早上好')
        self.assertEqual(self.profiles.address('group@chatroom','queen','尊重称呼，在呢'),'尊重称呼，在呢')
        self.assertEqual(self.profiles.address('different@chatroom','lele','早上好'),'早上好')
    def test_config_account_binding_and_current_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            path.write_text(json.dumps({'account_id':'me','group_id':'group@chatroom','people':self.people}),encoding='utf8')
            self.assertTrue(GroupProfiles.load('me',path).applies('group@chatroom'))
            self.assertFalse(GroupProfiles.load('someone-else',path).applies('group@chatroom'))
        self.members=[m for m in self.members if m['username']!='queen']
        self.assertNotIn('示例甲',self.context('SameNickname是谁',sender='caller'))
    def test_colliding_mention_never_guesses_wrong_person(self):
        db=Mock();db.get_group_members.return_value=self.members
        roster=build_mention_roster(db,'group@chatroom','caller','me','帮我@SameNickname说句话',
                                   group_aliases=self.profiles.group_aliases('group@chatroom'))
        self.assertEqual(roster.request_status,'ambiguous')
        roster=build_mention_roster(db,'group@chatroom','caller','me','帮我@SameNickname说句话',
                                   at_ids={'me','other'},group_aliases=self.profiles.group_aliases('group@chatroom'))
        self.assertEqual(roster.request_status,'ready')
        self.assertEqual(roster.requested,{'other'})
        roster=build_mention_roster(db,'group@chatroom','caller','me','帮我@友好称呼问好',
                                   group_aliases=self.profiles.group_aliases('group@chatroom'))
        self.assertEqual(roster.request_status,'ready')
        self.assertEqual(roster.requested,{'lele'})

    def test_identity_questions_resolve_target_and_avoid_ambiguous_names(self):
        for question in ('示例丁是谁？','友好称呼是谁','谁是示例丁','群昵称甲叫什么名字？','示例丁是什么人'):
            self.assertEqual(self.profiles.identity_question('group@chatroom',question,(),self.members,'me'),(True,'lele'))
        self.assertEqual(self.profiles.identity_question('group@chatroom','SameNickname是谁',(),self.members,'me'),(True,None))
        self.assertEqual(self.profiles.identity_question('group@chatroom','群昵称SameNickname是谁',(),self.members,'me'),(True,'other'))
        self.assertEqual(self.profiles.identity_question('group@chatroom','微信昵称SameNickname是谁',(),self.members,'me'),(True,'queen'))
        self.assertEqual(self.profiles.identity_question('group@chatroom','@SameNickname是谁',{'other'},self.members,'me'),(True,'other'))
        self.assertEqual(self.profiles.identity_question('group@chatroom','示例丁今天来了',(),self.members,'me'),(False,None))
        self.assertEqual(self.profiles.identity_question('else@chatroom','示例丁是谁',(),self.members,'me'),(False,None))

if __name__=='__main__': unittest.main()
