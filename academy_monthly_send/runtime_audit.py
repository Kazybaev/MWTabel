"""Run the pinned draft graph with Dify's 1.14.2 GraphEngine and mock HTTP transport.

The container must have no external network. Draft data is read only; real secrets are
discarded and replaced by synthetic values. Nothing is written to Dify's database.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml

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


TARGET_DRAFT_ID = '1206a106-ff36-4b89-b718-eea7203d3645'
TARGET_APP_ID = '46741506-cdaa-456b-8e04-1c5c5c3a0e7a'
TARGET_PATH = Path('/audit/monthly_send.yml')
INPUTS_PATH = Path('/audit/example_inputs.json')


class MockHttpTransport:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []

    @property
    def request_error(self):
        return httpx.RequestError

    @property
    def max_retries_exceeded_error(self):
        return ValueError

    def post(self, url, max_retries=0, **kwargs):
        self.calls.append(url)
        assert max_retries == 0, 'unexpected transport retry'
        assert kwargs.get('headers', {}).get('Authorization') in (
            'Bearer synthetic-meta-token',
            'Bearer synthetic-callback-token',
        )
        body = json.loads(kwargs.get('content') or '{}')
        if url == 'https://mock.invalid/meta':
            assert body['template']['name'] == 'student_weekly_reports_v4'
            assert body['type'] == 'template'
            assert body['template']['language']['code'] == 'ky_KG'
            values = [item['text'] for item in body['template']['components'][0]['parameters']]
            assert values == [
                'ИИ-30', 'Шакеева Айдана', 'Сентябрь',
                '“5” – 0 даана', '“4” – 3 даана', '“3” – 10 даана', '“2” – 0 даана',
                'Белгиленген калуулар (Н): 0; белги коюлбаган сабактар: 15.',
            ]
            if self.scenario == 'timeout':
                raise httpx.ReadTimeout('synthetic provider timeout')
            if self.scenario == 'refusal':
                return HttpResponse(status_code=400, content=b'{"error":{"code":132000}}', url=url)
            if self.scenario == 'no_id':
                return HttpResponse(status_code=200, content=b'{"messages":[]}', url=url)
            if self.scenario == 'server_error':
                return HttpResponse(status_code=503, content=b'{"error":{"code":1}}', url=url)
            return HttpResponse(status_code=200, content=b'{"messages":[{"id":"wamid.mock-runtime"}]}', url=url)
        assert url == 'https://mock.invalid/callback', 'unexpected HTTP destination'
        assert body['delivery']['event'] == 'student_monthly_report_result'
        if self.scenario == 'callback_failure':
            raise httpx.ReadTimeout('synthetic callback timeout')
        return HttpResponse(status_code=200, content=b'{"ok":true}', url=url)

    def get(self, *args, **kwargs):
        raise AssertionError('GET is forbidden in this graph')

    head = get
    put = get
    delete = get
    patch = get


class MockChildEngine:
    def __init__(self, transport):
        self.transport = transport

    def build_child_engine(self, *, workflow_id, graph_init_params, parent_graph_runtime_state, root_node_id, variable_pool=None):
        child_state = GraphRuntimeState(
            variable_pool=variable_pool or parent_graph_runtime_state.variable_pool,
            start_at=time.perf_counter(),
            execution_context=parent_graph_runtime_state.execution_context,
        )
        with patch('core.workflow.node_factory.build_dify_model_access', return_value=(None, None)):
            factory = DifyNodeFactory(graph_init_params=graph_init_params, graph_runtime_state=child_state)
        factory._http_request_http_client = self.transport
        child_graph = Graph.init(graph_config=graph_init_params.graph_config, node_factory=factory, root_node_id=root_node_id)
        return GraphEngine(
            workflow_id=workflow_id,
            graph=child_graph,
            graph_runtime_state=child_state,
            command_channel=InMemoryChannel(),
            config=GraphEngineConfig(min_workers=1, max_workers=1),
            child_engine_builder=self,
        )


def load_graph():
    snapshot = os.environ.get('ACADEMY_AUDIT_GRAPH_PATH')
    if snapshot:
        rows = Path(snapshot).read_text().splitlines()
        assert len(rows) == 1
        draft = json.loads(rows[0])
        assert draft['id'] == TARGET_DRAFT_ID and draft['app_id'] == TARGET_APP_ID and draft['version'] == 'draft'
        variables = draft['environment_variables']
        variables = json.loads(variables) if isinstance(variables, str) else variables
        assert variables['ACADEMY_SEND_ENABLED']['value'] == 'false'
        graph = draft['graph']
        return json.loads(graph) if isinstance(graph, str) else graph
    dsl = yaml.safe_load(TARGET_PATH.read_text())
    assert next(x['value'] for x in dsl['workflow']['environment_variables'] if x['name'] == 'ACADEMY_SEND_ENABLED') == 'false'
    return dsl['workflow']['graph']


def run_case(graph, inputs, scenario):
    root_id = get_default_root_node_id(graph)
    pool = VariablePool()
    add_variables_to_pool(
        pool,
        build_system_variables(
            user_id='synthetic-user',
            app_id=TARGET_APP_ID,
            workflow_id=TARGET_DRAFT_ID,
            workflow_run_id='synthetic-run',
            files=[],
        ),
    )
    add_node_inputs_to_pool(pool, node_id=root_id, inputs=inputs)
    for key, value in {
        'ACADEMY_SEND_ENABLED': 'false' if scenario == 'gate_closed' else 'true',
        'META_WHATSAPP_ACCESS_TOKEN': 'synthetic-meta-token',
        'BACKEND_REPORT_CALLBACK_TOKEN': 'synthetic-callback-token',
        'META_MESSAGES_URL': 'https://mock.invalid/meta',
        'BACKEND_REPORT_URL': 'https://mock.invalid/callback',
    }.items():
        pool.add(('env', key), value)
    state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    init_params = GraphInitParams(
        workflow_id=TARGET_DRAFT_ID,
        graph_config=graph,
        run_context=build_dify_run_context(
            tenant_id='synthetic-tenant',
            app_id=TARGET_APP_ID,
            user_id='synthetic-user',
            user_from=UserFrom.ACCOUNT,
            invoke_from=InvokeFrom.DEBUGGER,
        ),
        call_depth=0,
    )
    with patch('core.workflow.node_factory.build_dify_model_access', return_value=(None, None)):
        factory = DifyNodeFactory(graph_init_params=init_params, graph_runtime_state=state)
    transport = MockHttpTransport(scenario)
    factory._http_request_http_client = transport
    graph_obj = Graph.init(graph_config=graph, node_factory=factory, root_node_id=root_id)
    engine = GraphEngine(
        workflow_id=TARGET_DRAFT_ID,
        graph=graph_obj,
        graph_runtime_state=state,
        command_channel=InMemoryChannel(),
        config=GraphEngineConfig(min_workers=1, max_workers=1),
        child_engine_builder=MockChildEngine(transport),
    )
    try:
        events = list(engine.run())
    except RuntimeError:
        if scenario != 'gate_closed':
            raise
        assert transport.calls == []
        print('gate_closed:PASS http_calls=0')
        return
    event_names = [type(event).__name__ for event in events]
    end_id = next(node['id'] for node in graph['nodes'] if node['data']['type'] == 'end')
    result = pool.get_by_prefix(end_id)
    safe_result = {key: getattr(value, 'value', value) for key, value in result.items()}
    expected = {'accepted': 'accepted', 'refusal': 'failed', 'timeout': 'unknown', 'callback_failure': 'accepted', 'no_id': 'unknown', 'server_error': 'unknown'}[scenario]
    actual = safe_result.get('provider_status')
    print(
        f'{scenario}: observed_status={actual} expected_status={expected} '
        f'provider_http_status={safe_result.get("provider_http_status")} '
        f'callback_status={safe_result.get("callback_status_code")} http_calls={len(transport.calls)}'
    )
    assert actual == expected, (scenario, event_names, sorted(safe_result))
    assert transport.calls == ['https://mock.invalid/meta', 'https://mock.invalid/callback']
    classifier = pool.get_by_prefix('1791954000001')
    classified = {key: getattr(value, 'value', value) for key, value in classifier.items()}
    if scenario == 'refusal':
        assert safe_result.get('provider_http_status') == 400
        assert classified.get('provider_error_code') == '132000'
    if scenario == 'timeout':
        assert safe_result.get('provider_http_status') == 0
    if scenario == 'callback_failure':
        assert safe_result.get('callback_status_code') in (0, '0')
    if scenario in ('accepted', 'callback_failure'):
        assert safe_result.get('provider_message_id') == 'wamid.mock-runtime'
    print(f'{scenario}:PASS events={len(events)} http_calls={len(transport.calls)} status={expected}')


def main():
    graph = load_graph()
    inputs = json.loads(INPUTS_PATH.read_text())['inputs']
    failures = []
    for scenario in ('gate_closed', 'accepted', 'refusal', 'timeout', 'no_id', 'server_error', 'callback_failure'):
        try:
            run_case(graph, inputs, scenario)
        except AssertionError as error:
            failures.append(scenario)
            print(f'{scenario}:FAIL {type(error).__name__}')
    if failures:
        raise SystemExit('failed_scenarios=' + ','.join(failures))


if __name__ == '__main__':
    main()
