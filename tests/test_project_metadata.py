import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from codex_sync_desktop.core.backups import create_import_transaction, finish_import_transaction, rollback_import_transaction
from codex_sync_desktop.core.projects import MEMBERSHIP_FILE, combine_projects, infer_project, project_label, read_project_context, session_project
from codex_sync_desktop.core.sessions import apply_import, export_sanitized_sessions, plan_all_import
from tests.helpers import create_state_database, write_session


def project_state(home, assignments):
    home.mkdir(parents=True, exist_ok=True)
    (home/'.codex-global-state.json').write_text(json.dumps({
        'local-projects': {'p1': {'name':'模型测试','rootPaths':['/work/models']}, 'p2': {'name':'模型测试','rootPaths':['/elsewhere/models']}},
        'thread-project-assignments': {identity:{'projectId':project,'projectKind':'local'} for identity,project in assignments.items()},
        'projectless-thread-ids':['personal'],
    },ensure_ascii=False))


class ProjectMetadataTests(TestCase):
    def test_export_groups_same_project_across_different_working_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'source';vault=root/'vault'
            project_state(home, {'one':'p1','two':'p1','three':'p2'})
            for identity,cwd in [('one','/work/models/a'),('two','/different/cwd'),('three','/elsewhere/models'),('personal','/work/models')]:
                write_session(home,identity,cwd=cwd)
            before=(home/'.codex-global-state.json').read_bytes()
            export_sanitized_sessions(home,vault,'device')
            manifest=json.loads((vault/'sessions-text/devices/device/manifest.json').read_text())
            self.assertEqual(manifest['project_metadata_format'],1)
            entries={entry['task_id']:entry['project'] for entry in manifest['sessions']}
            self.assertEqual(entries['one']['group_id'], entries['two']['group_id'])
            self.assertNotEqual(entries['one']['group_id'], entries['three']['group_id'])
            self.assertEqual(entries['personal']['status'],'unassigned')
            group=next(group for group in manifest['projects'] if group['group_id']=='local:p1')
            self.assertEqual(set(group['session_ids']),{'one','two'})
            self.assertEqual((home/'.codex-global-state.json').read_bytes(),before)
            plan=plan_all_import(root/'target',vault)
            self.assertEqual(next(item for item in plan.items if item.task_id=='two').project['name'],'模型测试')

    def test_native_database_assignment_wins_and_preserves_root_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            project_state(home, {'one':'p2'})
            database=create_state_database(home)
            with sqlite3.connect(database) as connection:
                connection.executescript('''ALTER TABLE threads ADD COLUMN project_id TEXT;
                    CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT);
                    CREATE TABLE project_roots(project_id TEXT,position INTEGER,path TEXT);
                    INSERT INTO projects VALUES ('native','真实项目');
                    INSERT INTO project_roots VALUES ('native',0,'/real/root');
                    INSERT INTO threads(id,rollout_path,created_at,updated_at,source,model_provider,cwd,title,sandbox_policy,approval_mode,project_id)
                    VALUES ('one','path',1,1,'app','openai','/other','title','{}','never','native');''')
            project=session_project(read_project_context(home),'one','/other')
            self.assertEqual(project['project_id'],'native')
            self.assertEqual(project['name'],'真实项目')
            self.assertEqual(project['roots'],['/real/root'])

    def test_directory_inference_is_explicit_and_respects_path_boundaries(self):
        context={'projects':{'p':{'group_id':'local:p','name':'项目','roots':['/work/project'],'status':'confirmed'}},'assignments':{},'projectless':set(),'saved':{}}
        inferred=session_project(context,'one','/work/project/subdir')
        self.assertEqual(inferred['status'],'inferred')
        self.assertIn('目录推断',project_label(inferred))
        self.assertNotEqual(infer_project('/work/project-copy',context['projects'].values())['group_id'],'local:p')
        self.assertNotEqual(infer_project('/one/demo')['group_id'],infer_project('/two/demo')['group_id'])
        self.assertEqual(infer_project('')['status'],'unknown')

    def test_conflicting_source_projects_are_not_silently_merged(self):
        one={'group_id':'local:p1','name':'P1','status':'confirmed'}
        two={'group_id':'local:p2','name':'P2','status':'confirmed'}
        self.assertEqual(combine_projects([one,two])['status'],'conflict')
        self.assertEqual(combine_projects([one,dict(two,status='inferred')])['group_id'],'local:p1')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for device,project in [('a','p1'),('b','p2')]:
                home=root/device;project_state(home,{'same':project});write_session(home,'same')
                export_sanitized_sessions(home,root/'vault',device)
            plan=plan_all_import(root/'target',root/'vault')
            self.assertEqual(plan.items[0].project['status'],'conflict')
            self.assertEqual(len(plan.items[0].project['candidates']),2)

    def test_import_persists_source_project_for_reexport_and_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target';vault=root/'vault'
            project_state(source,{'new':'p1'});write_session(source,'new')
            export_sanitized_sessions(source,vault,'source')
            create_state_database(target)
            # Existing provenance must remain unchanged while new metadata is added.
            (target/MEMBERSHIP_FILE).write_text(json.dumps({'format':1,'sessions':{'old':{'group_id':'local:old','name':'本机项目','status':'confirmed'}}}))
            before=(target/MEMBERSHIP_FILE).read_bytes()
            plan=plan_all_import(target,vault)
            transaction=create_import_transaction(target,plan)
            result=apply_import(plan);finish_import_transaction(transaction,result['counts'])
            recorded=json.loads((target/MEMBERSHIP_FILE).read_text())['sessions']
            self.assertEqual(recorded['old']['name'],'本机项目')
            self.assertEqual(recorded['new']['name'],'模型测试')
            self.assertFalse((target/'.codex-global-state.json').exists())
            export_sanitized_sessions(target,root/'second-vault','target')
            manifest=json.loads((root/'second-vault/sessions-text/devices/target/manifest.json').read_text())
            self.assertEqual(manifest['sessions'][0]['project']['group_id'],'local:p1')
            rollback_import_transaction(target,transaction)
            self.assertEqual((target/MEMBERSHIP_FILE).read_bytes(),before)

    def test_protected_sessions_do_not_gain_or_change_project_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target';vault=root/'vault'
            project_state(source,{'same':'p1'});write_session(source,'same')
            export_sanitized_sessions(source,vault,'source')
            write_session(target,'same',cwd='/local/project')
            project_state(target,{'same':'p2'})
            before=(target/'.codex-global-state.json').read_bytes()
            plan=plan_all_import(target,vault)
            self.assertEqual(plan.counts,{'skipped-existing':1})
            apply_import(plan)
            self.assertFalse((target/MEMBERSHIP_FILE).exists())
            self.assertEqual((target/'.codex-global-state.json').read_bytes(),before)

    def test_legacy_manifests_fall_back_to_honest_cwd_annotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);write_session(root/'source','legacy',cwd='/work/legacy')
            export_sanitized_sessions(root/'source',root/'vault','source')
            path=root/'vault/sessions-text/devices/source/manifest.json'
            data=json.loads(path.read_text());data['sessions'][0].pop('project');data.pop('projects');path.write_text(json.dumps(data))
            project=plan_all_import(root/'target',root/'vault').items[0].project
            self.assertEqual(project['name'],'legacy')
            self.assertEqual(project['status'],'inferred')

    def test_legacy_project_id_alias_resolves_to_native_group(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            project_state(home, {'one':'p1'})
            path=home/'.codex-global-state.json'
            state=json.loads(path.read_text())
            state['app-server-project-id-by-legacy-project-id-by-host']={'local:'+str(home):{'p1':'native'}}
            path.write_text(json.dumps(state))
            context=read_project_context(home)
            self.assertEqual(session_project(context,'one','/other')['group_id'],'local:native')
            self.assertEqual(session_project(context,'one','/other')['name'],'模型测试')
