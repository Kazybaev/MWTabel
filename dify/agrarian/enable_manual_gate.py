"""Enable and publish only the verified agrarian Dify gate through console API."""
import hashlib
import json
import subprocess
from pathlib import Path

import publish_checked as checked
import sync_draft as console

APP = checked.APP_ID
OLD_PUBLISHED = '835ebd10-d71d-4beb-b0ed-f72c8eaad13b'
BACKUP = Path('/root/mwtabel-private/agrarian-manual-route-20261118')


def stop(message):
    raise SystemExit('STOP: ' + message)


def queue_count():
    code = (
        "from django.db import connection,transaction; "
        "from tabel_app.models import MonthlyStudentReportBatch,MonthlyStudentReportBatchItem; "
        "\nwith transaction.atomic():\n"
        " with connection.cursor() as c: c.execute('SET TRANSACTION READ ONLY')\n"
        " print('AGRARIAN_BATCHES=' + str(MonthlyStudentReportBatch.objects.filter(requested_filters__workflow_route='agrarian').count()))\n"
        " print('AGRARIAN_ITEMS=' + str(MonthlyStudentReportBatchItem.objects.filter(batch__requested_filters__workflow_route='agrarian').count()))"
    )
    result = subprocess.run(['docker', 'exec', 'mwtabel-web-1', 'python', 'manage.py', 'shell', '-c', code],
                            capture_output=True, text=True)
    if result.returncode:
        stop('read-only agrarian queue preflight failed')
    if 'AGRARIAN_BATCHES=0' not in result.stdout or 'AGRARIAN_ITEMS=0' not in result.stdout:
        stop('agrarian batch or item exists')


def main():
    for name in ('mwtabel.env.before', 'dify-draft.before.private.json',
                 'dify-published.before.private.json', 'production-before.dump', 'ROLLBACK.md'):
        if not (BACKUP / name).is_file():
            stop('protected rollback artifact missing: ' + name)
    identity = json.loads(console.IDENTITY.read_text())
    if identity.get('app_id') != APP or identity.get('published_workflow_id') != OLD_PUBLISHED:
        stop('identity manifest changed')
    key_path = BACKUP / 'dify-api-key.private'
    if not key_path.is_file() or key_path.stat().st_mode & 0o077:
        stop('private agrarian app key missing')
    key = key_path.read_text().strip()
    if len(key) < 24:
        stop('private agrarian app key empty')
    token = console.read_secret('console-session.private')
    csrf = console.read_secret('console-csrf.private')
    path = '/apps/' + APP
    status, keys = console.request(path + '/api-keys', 'GET', token, csrf)
    if status != 200 or sum(item.get('token') == key for item in keys.get('data', [])) != 1:
        stop('private API key binding to exact app failed')
    rows = console.db_rows()
    if len(rows) != 1 or rows[0][0] != APP or rows[0][2] != console.TENANT or rows[0][3] != 'workflow' or rows[0][4] != OLD_PUBLISHED:
        stop('Dify app identity or published ID changed')
    desired = json.loads(console.GRAPH.read_text())
    expected = checked.functional(desired)
    status, draft = console.request(path + '/workflows/draft', 'GET', token, csrf)
    if status != 200 or draft.get('id') != identity.get('draft_id') or checked.functional(draft['graph']) != expected:
        stop('draft identity or graph drift')
    status, published = console.request(path + '/workflows/publish', 'GET', token, csrf)
    if status != 200 or published.get('id') != OLD_PUBLISHED or checked.functional(published['graph']) != expected:
        stop('published identity or graph drift')
    draft_env = checked.env_mapping(draft['environment_variables'])
    published_env = checked.env_mapping(published['environment_variables'])
    sources = checked.sender_config()
    for name in checked.KINDS:
        if draft_env[name]['id'] != published_env[name]['id'] or draft_env[name]['value'] != published_env[name]['value']:
            stop('draft/published environment drift: ' + name)
        if name == 'AGRARIAN_SEND_ENABLED':
            if draft_env[name]['value'] != 'false': stop('old send gate changed')
        elif checked.KINDS[name] == 'secret':
            if draft_env[name]['value'] != '*' * 20: stop('secret mask or emptiness changed')
        elif draft_env[name]['value'] != sources[name]:
            stop('sender/callback URL source changed')
    queue_count()
    if checked.sql("SELECT count(*) FROM workflow_runs WHERE app_id='" + APP + "'") != '0':
        stop('unexpected workflow run before enable')
    env = [dict(item, value='true' if item['name'] == 'AGRARIAN_SEND_ENABLED' else item['value'])
           for item in draft['environment_variables']]
    payload = {'graph': desired, 'features': draft['features'], 'hash': draft.get('hash'),
               'environment_variables': env, 'conversation_variables': draft.get('conversation_variables', [])}
    status, result = console.request(path + '/workflows/draft', 'POST', token, csrf, payload)
    if status != 200 or result.get('result') != 'success': stop('draft gate write failed: HTTP ' + str(status))
    status, after = console.request(path + '/workflows/draft', 'GET', token, csrf)
    if status != 200 or after.get('id') != draft['id'] or checked.functional(after['graph']) != expected:
        stop('draft reread graph mismatch')
    actual = checked.env_mapping(after['environment_variables'])
    for name in checked.KINDS:
        if actual[name]['id'] != draft_env[name]['id']:
            stop('draft variable ID changed: ' + name)
        if name == 'AGRARIAN_SEND_ENABLED':
            if actual[name]['value'] != 'true': stop('draft gate did not enable')
        elif actual[name]['value'] != draft_env[name]['value']:
            stop('draft setting changed: ' + name)
    queue_count()
    status, result = console.request(path + '/workflows/publish', 'POST', token, csrf,
                                     {'marked_name': 'agrarian-manual', 'marked_comment': 'Manual route gate enabled'})
    if status != 200 or result.get('result') != 'success': stop('Dify publication failed: HTTP ' + str(status))
    status, new = console.request(path + '/workflows/publish', 'GET', token, csrf)
    if status != 200 or not new.get('id') or new['id'] == OLD_PUBLISHED or checked.functional(new['graph']) != expected:
        stop('published workflow reread failed')
    new_env = checked.env_mapping(new['environment_variables'])
    for name in checked.KINDS:
        if new_env[name]['id'] != draft_env[name]['id'] or new_env[name]['value'] != actual[name]['value']:
            stop('published environment mismatch: ' + name)
    if new_env['AGRARIAN_SEND_ENABLED']['value'] != 'true': stop('published gate is not true')
    if checked.sql("SELECT coalesce(workflow_id::text,'') FROM apps WHERE id='" + APP + "'") != new['id']:
        stop('app published workflow ID mismatch')
    if checked.sql("SELECT count(*) FROM workflow_runs WHERE app_id='" + APP + "'") != '0':
        stop('unexpected workflow run after enable')
    identity.update({'published_workflow_id': new['id'], 'previous_published_workflow_id': OLD_PUBLISHED,
                     'send_enabled': True, 'desired_graph_sha256': hashlib.sha256(console.GRAPH.read_bytes()).hexdigest()})
    console.save_identity(identity)
    print('published_workflow_id=' + new['id'])
    print('graph_match=True gate=true settings_preserved=True runs=0')


if __name__ == '__main__':
    main()
