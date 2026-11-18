"""Run a copy of the prepared graph in Dify GraphEngine with mock HTTP only."""

import copy
import json
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

APP = "00000000-0000-4000-8000-000000000001"
WORKFLOW = "00000000-0000-4000-8000-000000000002"
ROOT = Path("/audit")


class Transport:
    request_error = Exception
    max_retries_exceeded_error = TimeoutError

    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []
        self.callback = None

    def post(self, url, **kwargs):
        self.calls.append(url)
        if url == "https://mock.invalid/meta":
            try:
                message = json.loads(kwargs["content"])
            except ValueError:
                print('META_CONTENT_PREFIX', repr(kwargs.get('content', b'')[:160]), file=sys.stderr)
                raise
            params = message["template"]["components"][0]["parameters"]
            assert len(params) == 24
            assert all(p["text"] == " ".join(p["text"].split()) for p in params)
            assert all(not any(c in p["text"] for c in "\r\n\t") for p in params)
            if self.scenario == "timeout":
                raise TimeoutError("mock timeout")
            if self.scenario == "http_400":
                return HttpResponse(status_code=400, content=b'{"error":{"code":131000}}', url=url)
            if self.scenario == "without_id":
                return HttpResponse(status_code=200, content=b'{"messages":[{}]}', url=url)
            return HttpResponse(status_code=200, content=b'{"messages":[{"id":"wamid.mock"}]}', url=url)
        assert url == "https://mock.invalid/backend", url
        try:
            self.callback = json.loads(kwargs["content"])
        except ValueError:
            print('CALLBACK_CONTENT_PREFIX', repr(kwargs.get('content', b'')[:160]), file=sys.stderr)
            raise
        code = 503 if self.scenario == "callback_failure" else 200
        return HttpResponse(status_code=code, content=b'{"ok":true}', url=url)

    def get(self, *args, **kwargs):
        raise AssertionError("Unexpected HTTP GET")

    head = put = patch = delete = get


class MockChildEngineBuilder:
    def __init__(self, transport):
        self.transport = transport

    def build_child_engine(self, *, workflow_id, graph_init_params, parent_graph_runtime_state, root_node_id, variable_pool=None):
        child_state = GraphRuntimeState(
            variable_pool=variable_pool if variable_pool is not None else parent_graph_runtime_state.variable_pool,
            start_at=time.perf_counter(),
            execution_context=parent_graph_runtime_state.execution_context,
        )
        with patch("core.workflow.node_factory.build_dify_model_access", return_value=(None, None)):
            factory = DifyNodeFactory(graph_init_params=graph_init_params, graph_runtime_state=child_state)
        factory._http_request_http_client = self.transport
        child_graph = Graph.init(graph_config=graph_init_params.graph_config, node_factory=factory, root_node_id=root_node_id)
        return GraphEngine(
            workflow_id=workflow_id, graph=child_graph, graph_runtime_state=child_state,
            command_channel=InMemoryChannel(), config=GraphEngineConfig(min_workers=1, max_workers=1),
            child_engine_builder=self,
        )


def report_input():
    report = copy.deepcopy(json.loads((ROOT / "docs/agrarian_report_examples.json").read_text())["examples"]["full"])
    report["student"]["id"] = 1
    report["student"]["full_name"] = "Тестовый студент"
    report["student"]["parent_phone"] = "+996700000000"
    report["correlation"] = {"dispatch_id": 1, "attempt_id": 1, "batch_item_id": 1}
    return report


def run(graph, report, scenario, enabled):
    root = get_default_root_node_id(graph)
    pool = VariablePool()
    add_variables_to_pool(pool, build_system_variables(user_id="test", app_id=APP, workflow_id=WORKFLOW, workflow_run_id="test", files=[]))
    pool.add(("env", "AGRARIAN_SEND_ENABLED"), "true" if enabled else "false")
    pool.add(("env", "META_MESSAGES_URL"), "https://mock.invalid/meta")
    pool.add(("env", "BACKEND_REPORT_URL"), "https://mock.invalid/backend")
    pool.add(("env", "META_WHATSAPP_ACCESS_TOKEN"), "synthetic-meta-token")
    pool.add(("env", "BACKEND_REPORT_CALLBACK_TOKEN"), "synthetic-callback-token")
    inputs = {
        "report": report,
        "student_name": report["student"]["full_name"],
        "recipient_name": report["student"]["parent_name"],
        "recipient_phone": report["student"]["parent_phone"],
        "group_name": report["main_group"]["name"] or report["group"]["course_name"],
        "month": report["period"]["month"],
    }
    add_node_inputs_to_pool(pool, node_id=root, inputs=inputs)
    state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    params = GraphInitParams(workflow_id=WORKFLOW, graph_config=graph, run_context=build_dify_run_context(tenant_id="test", app_id=APP, user_id="test", user_from=UserFrom.ACCOUNT, invoke_from=InvokeFrom.DEBUGGER), call_depth=0)
    with patch("core.workflow.node_factory.build_dify_model_access", return_value=(None, None)):
        factory = DifyNodeFactory(graph_init_params=params, graph_runtime_state=state)
    transport = Transport(scenario)
    factory._http_request_http_client = transport
    engine = GraphEngine(workflow_id=WORKFLOW, graph=Graph.init(graph_config=graph, node_factory=factory, root_node_id=root), graph_runtime_state=state, command_channel=InMemoryChannel(), config=GraphEngineConfig(min_workers=1, max_workers=1), child_engine_builder=MockChildEngineBuilder(transport))
    try:
        events = [type(event).__name__ for event in engine.run()]
    except RuntimeError as exc:
        events = ["RuntimeError:" + str(exc)]
    return transport, events


def main():
    graph = json.loads((ROOT / "dify/agrarian/workflow_graph.json").read_text())
    report = report_input()
    for scenario in ("gate_false", "success", "http_400", "timeout", "without_id", "callback_failure"):
        transport, events = run(graph, report, scenario, scenario != "gate_false")
        if scenario == "gate_false":
            assert transport.calls == [], (scenario, events, transport.calls)
            assert any("AGRARIAN_SEND_ENABLED=false" in event for event in events), events
        else:
            assert transport.calls.count("https://mock.invalid/meta") == 1, (scenario, events, transport.calls)
            assert transport.calls.count("https://mock.invalid/backend") == 1, (scenario, events, transport.calls)
            assert len(transport.calls) == 2 and set(transport.calls) == {"https://mock.invalid/meta", "https://mock.invalid/backend"}
            expected = {"success": "accepted", "http_400": "failed", "timeout": "unknown", "without_id": "unknown", "callback_failure": "accepted"}[scenario]
            assert transport.callback and transport.callback["delivery"]["provider_status"] == expected, (scenario, events, transport.callback and {"status": transport.callback["delivery"].get("provider_status"), "code": transport.callback.get("meta_status_code")})
            expected_code = {"success": 200, "http_400": 400, "timeout": 0, "without_id": 200, "callback_failure": 200}[scenario]
            assert transport.callback["meta_status_code"] == expected_code
            assert transport.callback["delivery"]["report"]["correlation"] == report["correlation"]
            assert events[-1] == ("GraphRunPartialSucceededEvent" if scenario == "callback_failure" else "GraphRunSucceededEvent"), events
        print(f"{scenario}: PASS outbound_calls={len(transport.calls)} events={events[-1] if events else 'none'}")


if __name__ == "__main__":
    main()
