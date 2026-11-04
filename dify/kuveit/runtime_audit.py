"""Run the published Kuwait graph with local formatter and mock HTTP only."""

import copy
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom, build_dify_run_context
from core.workflow.node_factory import DifyNodeFactory, get_default_root_node_id
from core.workflow.system_variables import build_system_variables
from core.workflow.variable_pool_initializer import add_node_inputs_to_pool, add_variables_to_pool
from graphon.entities import GraphInitParams
from graphon.graph import Graph
from graphon.graph_engine import GraphEngine, GraphEngineConfig
from graphon.graph_engine.command_channels import InMemoryChannel
from graphon.http import HttpResponse
from graphon.runtime import GraphRuntimeState, VariablePool

APP = '7237fd4d-3859-4b73-b478-61c22df586ce'
WORKFLOW = '133b3a19-0eb7-470c-bc25-2b4518568e3c'


class Transport:
    request_error = Exception
    max_retries_exceeded_error = ValueError

    def __init__(self):
        self.calls = []
        self.messages = []

    def post(self, url, **kwargs):
        self.calls.append(url)
        if url == 'https://mock.invalid/meta':
            body = json.loads(kwargs['content'])
            self.messages.append(body)
            assert body['template']['name'] == 'student_monthsly_send_v5'
            return HttpResponse(status_code=200, content=b'{"messages":[{"id":"wamid.mock"}]}', url=url)
        assert url == 'https://mock.invalid/backend', url
        return HttpResponse(status_code=200, content=b'{"ok":true}', url=url)

    def get(self, *args, **kwargs):
        raise AssertionError('Unexpected HTTP GET')

    head = put = patch = delete = get


def run(graph, report):
    root = get_default_root_node_id(graph)
    pool = VariablePool()
    add_variables_to_pool(pool, build_system_variables(user_id='test', app_id=APP, workflow_id=WORKFLOW, workflow_run_id='test', files=[]))
    add_node_inputs_to_pool(pool, node_id=root, inputs={'report': report})
    state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    params = GraphInitParams(workflow_id=WORKFLOW, graph_config=graph, run_context=build_dify_run_context(tenant_id='test', app_id=APP, user_id='test', user_from=UserFrom.ACCOUNT, invoke_from=InvokeFrom.DEBUGGER), call_depth=0)
    with patch('core.workflow.node_factory.build_dify_model_access', return_value=(None, None)):
        factory = DifyNodeFactory(graph_init_params=params, graph_runtime_state=state)
    transport = Transport()
    factory._http_request_http_client = transport
    engine = GraphEngine(workflow_id=WORKFLOW, graph=Graph.init(graph_config=graph, node_factory=factory, root_node_id=root), graph_runtime_state=state, command_channel=InMemoryChannel(), config=GraphEngineConfig(min_workers=1, max_workers=1))
    try:
        events = list(engine.run())
    except RuntimeError as error:
        return transport, [str(error)]
    return transport, [type(event).__name__ for event in events]


def main():
    graph = json.loads(Path('/audit/graph.json').read_text())
    code = Path('/audit/formatter.py').read_text()
    for node in graph['nodes']:
        data = node['data']
        if data['type'] == 'code':
            data['code'] = code
        if data['type'] == 'http-request':
            data['url'] = 'https://mock.invalid/meta' if data['title'] == 'HTTP-запрос' else 'https://mock.invalid/backend'
            data['authorization'] = {'type': 'api-key', 'config': {'type': 'bearer', 'api_key': 'synthetic-token'}}
    rows = [json.loads(line)['payload'] for line in Path('/audit/payloads.jsonl').read_text().splitlines()]
    assert len(rows) == 3
    for index, report in enumerate(rows, 1):
        report['student']['full_name'] = 'Тестовый студент'
        report['student']['parent_name'] = 'Тестовый родитель'
        report['student']['parent_phone'] = '+996700000000'
        transport, events = run(graph, report)
        assert len(transport.messages) == 1, events
        params = transport.messages[0]['template']['components'][0]['parameters']
        values = [item['text'] for item in params]
        assert len(values) == 24 and values[18:23] == ['—'] * 5
        print(f'batch11_item_{index}: PASS calls={len(transport.calls)} parameters={len(values)} fourth={values[18:23]}')
    four = copy.deepcopy(rows[0])
    fourth = copy.deepcopy(four['subjects'][0])
    fourth['name'] = 'Тестовый четвёртый предмет'
    four['subjects'].append(fourth)
    transport, events = run(graph, four)
    assert len(transport.messages) == 1, events
    values = [item['text'] for item in transport.messages[0]['template']['components'][0]['parameters']]
    assert len(values) == 24 and values[18] == 'Тестовый четвёртый предмет'
    print(f'four_subjects: PASS calls={len(transport.calls)} parameters={len(values)} fourth={values[18:23]}')
    for label, subjects in [('empty', []), ('five', four['subjects'] + [fourth]), ('invalid', 'wrong')]:
        bad = copy.deepcopy(rows[0])
        bad['subjects'] = subjects
        transport, events = run(graph, bad)
        assert not transport.calls and any('ValueError' in event for event in events), (label, events)
        print(f'{label}: PASS http_calls=0')


if __name__ == '__main__':
    main()
