"""Guarded console-only update and publication of the exact agrarian app.

Reads verified sender and backend configuration without printing secret values.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import sync_draft as console

APP_ID = 'a67fd500-51ca-486a-9088-7b9bda934563'
SENDER_APP_ID = '7237fd4d-3859-4b73-b478-61c22df586ce'
SENDER_SNAPSHOT = Path('/root/mwtabel-private/kuveit-formatter-20261107/published-console-after.private.json')
OLD_GRAPH_COMMIT = '84c0c62^'
KINDS = {
    'AGRARIAN_SEND_ENABLED': 'string',
    'META_WHATSAPP_ACCESS_TOKEN': 'secret',
    'BACKEND_REPORT_CALLBACK_TOKEN': 'secret',
    'META_MESSAGES_URL': 'string',
    'BACKEND_REPORT_URL': 'string',
}


def stop(message):
    raise SystemExit('STOP: ' + message)


def run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        stop('read-only source command failed; details withheld')


def sql(query):
    return run(['docker', 'exec', '-e', 'PGOPTIONS=-c default_transaction_read_only=on',
                'docker-db_postgres-1', 'psql', '-U', 'postgres', '-d', 'dify',
                '-X', '-q', '-A', '-t', '-c', query])


def sender_config():
    row = sql("SELECT coalesce(workflow_id::text,'') FROM apps WHERE id='" + SENDER_APP_ID + "' AND name='kuveit' AND mode='workflow'")
    if len(row) != 36:
        stop('sender app or published workflow identity changed')
    current = json.loads(sql("SELECT graph FROM workflows WHERE id='" + row + "' AND app_id='" + SENDER_APP_ID + "' AND type='workflow'"))
    saved = json.loads(SENDER_SNAPSHOT.read_text())['graph']
    def http_configs(graph):
        return sorted((node['data'].get('url'), node['data'].get('authorization'))
                      for node in graph['nodes'] if node['data'].get('type') == 'http-request')
    if http_configs(current) != http_configs(saved) or len(http_configs(current)) != 2:
        stop('current sender HTTP configuration differs from private verified snapshot')
    urls = [node['data'] for node in current['nodes'] if node['data'].get('type') == 'http-request']
    callback = next((data for data in urls if urlparse(data.get('url', '')).path == '/api/report-logs/'), None)
    meta = next((data for data in urls if data is not callback), None)
    if callback is None or meta is None:
        stop('sender or callback HTTP node missing')
    meta_url = meta.get('url', '').strip()
    callback_url = callback.get('url', '').strip()
    meta_auth = meta.get('authorization', {})
    key = meta_auth.get('config', {}).get('api_key', '').strip()
    if (urlparse(meta_url).scheme != 'https' or not urlparse(meta_url).path.endswith('/messages')
            or meta_auth.get('type') != 'api-key' or meta_auth.get('config', {}).get('type') != 'bearer'
            or len(key) < 32 or key.startswith('{{#env.') or key == '[__HIDDEN__]'):
        stop('sender URL or authorization is not verified and nonempty')
    if urlparse(callback_url).scheme != 'https' or urlparse(callback_url).path != '/api/report-logs/':
        stop('callback URL does not match backend route')
    backend_token = run(['docker', 'exec', 'mwtabel-web-1', 'printenv', 'BACKEND_REPORT_CALLBACK_TOKEN'])
    if len(backend_token) < 32:
        stop('backend callback token is missing or too short')
    return {'META_WHATSAPP_ACCESS_TOKEN': key, 'BACKEND_REPORT_CALLBACK_TOKEN': backend_token,
            'META_MESSAGES_URL': meta_url, 'BACKEND_REPORT_URL': callback_url,
            'AGRARIAN_SEND_ENABLED': 'false'}


def functional(graph):
    fields = ('type', 'code', 'variables', 'outputs', 'url', 'authorization', 'body',
              'headers', 'retry_config', 'error_strategy')
    return {'nodes': {node['id']: {key: node['data'].get(key) for key in fields}
                      for node in graph['nodes']},
            'edges': sorted((edge['source'], edge['target']) for edge in graph['edges'])}


def env_mapping(items):
    if not isinstance(items, list) or len(items) != len(KINDS):
        stop('unexpected draft environment variable count')
    result = {item['name']: item for item in items}
    if set(result) != set(KINDS):
        stop('unexpected draft environment variable names')
    for name, item in result.items():
        if item.get('value_type') != KINDS[name] or not item.get('id'):
            stop('environment variable ID or type changed: ' + name)
    return result


def main():
    identity = json.loads(console.IDENTITY.read_text())
    if identity.get('app_id') != APP_ID or identity.get('tenant_id') != console.TENANT or identity.get('published') is not False:
        stop('local identity manifest changed')
    desired = json.loads(console.GRAPH.read_text())
    if len(desired['nodes']) != 11 or len(desired['edges']) != 9:
        stop('prepared graph shape changed')
    values = sender_config()
    token = console.read_secret('console-session.private')
    csrf = console.read_secret('console-csrf.private')
    app_path = '/apps/' + APP_ID
    status, app = console.request(app_path, 'GET', token, csrf)
    if status != 200 or not isinstance(app, dict) or app.get('id') != APP_ID:
        stop('console session or target app identity failed: HTTP ' + str(status))
    rows = console.db_rows()
    if len(rows) != 1 or rows[0][0] != APP_ID or rows[0][2] != console.TENANT or rows[0][3] != 'workflow' or rows[0][4]:
        stop('target app tenant, mode, published state or name changed')
    draft_path = app_path + '/workflows/draft'
    status, before = console.request(draft_path, 'GET', token, csrf)
    if status != 200 or not isinstance(before, dict) or before.get('id') != identity.get('draft_id') or before.get('version') != 'draft':
        stop('draft identity or session failed: HTTP ' + str(status))
    baseline = json.loads(run(['git', 'show', OLD_GRAPH_COMMIT + ':dify/agrarian/workflow_graph.json']))
    if functional(before['graph']) != functional(baseline):
        stop('draft graph differs from recorded baseline')
    old_env = env_mapping(before.get('environment_variables', []))
    if old_env['AGRARIAN_SEND_ENABLED'].get('value') != 'false':
        stop('existing draft gate changed')
    for name in KINDS:
        if name != 'AGRARIAN_SEND_ENABLED' and old_env[name].get('value') not in ('', None):
            stop('existing draft environment value changed: ' + name)
    env = []
    for name, item in old_env.items():
        updated = dict(item)
        updated['value'] = values[name]
        env.append(updated)
    payload = {'graph': desired, 'features': before['features'], 'hash': before.get('hash'),
               'environment_variables': env, 'conversation_variables': before.get('conversation_variables', [])}
    status, result = console.request(draft_path, 'POST', token, csrf, payload)
    if status != 200 or not isinstance(result, dict) or result.get('result') != 'success':
        stop('draft write failed: HTTP ' + str(status))
    status, after = console.request(draft_path, 'GET', token, csrf)
    if status != 200 or not isinstance(after, dict) or after.get('id') != before['id'] or after.get('version') != 'draft':
        stop('draft reread failed: HTTP ' + str(status))
    if functional(after['graph']) != functional(desired):
        stop('draft graph reread mismatch')
    actual = env_mapping(after.get('environment_variables', []))
    for name in KINDS:
        if actual[name]['id'] != old_env[name]['id'] or not actual[name].get('value'):
            stop('draft variable ID or nonempty value mismatch: ' + name)
        if name in ('AGRARIAN_SEND_ENABLED', 'META_MESSAGES_URL', 'BACKEND_REPORT_URL') and actual[name]['value'] != values[name]:
            stop('draft plain value mismatch: ' + name)
        if KINDS[name] == 'secret' and actual[name]['value'] not in (values[name], '[__HIDDEN__]'):
            stop('draft secret value was not retained: ' + name)
    if actual['AGRARIAN_SEND_ENABLED']['value'] != 'false':
        stop('draft send gate is not false')
    status, result = console.request(app_path + '/workflows/publish', 'POST', token, csrf,
                                     {'marked_name': 'agrarian-24', 'marked_comment': '24 parameters; sending disabled'})
    if status != 200 or not isinstance(result, dict) or result.get('result') != 'success':
        stop('publication failed: HTTP ' + str(status))
    status, published = console.request(app_path + '/workflows/publish', 'GET', token, csrf)
    if status != 200 or not isinstance(published, dict) or not published.get('id'):
        stop('published workflow reread failed: HTTP ' + str(status))
    if functional(published['graph']) != functional(desired):
        stop('published graph mismatch')
    published_env = env_mapping(published.get('environment_variables', []))
    if published_env['AGRARIAN_SEND_ENABLED'].get('value') != 'false':
        stop('published send gate is not false')
    row = sql("SELECT coalesce(workflow_id::text,'') FROM apps WHERE id='" + APP_ID + "' AND tenant_id='" + console.TENANT + "'")
    if row != published['id']:
        stop('published app workflow ID mismatch')
    runs = sql("SELECT count(*) FROM workflow_runs WHERE app_id='" + APP_ID + "'")
    if runs != '0':
        stop('unexpected agrarian workflow runs')
    identity.update({'draft_id': after['id'], 'desired_graph_sha256': hashlib.sha256(console.GRAPH.read_bytes()).hexdigest(),
                     'published': True, 'published_workflow_id': published['id']})
    console.save_identity(identity)
    print('published_workflow_id=' + published['id'])
    print('configuration: sender URL/auth nonempty; callback URL/token nonempty; gate=false; runs=0')


if __name__ == '__main__':
    main()
