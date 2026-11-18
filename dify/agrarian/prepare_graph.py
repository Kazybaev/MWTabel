"""Build a self-contained agrarian draft from a local Dify 1.14.2 graph skeleton.

The skeleton is read-only input. Its code, URLs, authorization and IDs are replaced.
"""

import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "formatter.py"
DEST_GRAPH = HERE / "workflow_graph.json"
DEST_CODE = HERE / "code_node.py"

START = "1800010000001"
FORMAT = "1800010000002"
ONCE = "1800010000003"
ITER = "1800010000004"
ITER_START = "1800010000004start"
META = "1800010000005"
CAPTURE = "1800010000006"
UNWRAP = "1800010000007"
CLASSIFY = "1800010000008"
CALLBACK = "1800010000009"
END = "1800010000010"

OLD_IDS = (
    "1782295814445", "1782296762177", "1791954000004", "1791954000002",
    "1791954000002start", "1782296965320", "1791954000003", "1791954000005",
    "1791954000001", "1784567000001", "1784202796519",
)
NEW_IDS = (START, FORMAT, ONCE, ITER, ITER_START, META, CAPTURE, UNWRAP, CLASSIFY, CALLBACK, END)

INPUTS = (
    ("report", "json_object", True),
    ("student_name", "text-input", True),
    ("recipient_name", "text-input", False),
    ("recipient_phone", "text-input", True),
    ("group_name", "text-input", True),
    ("mentor_name", "text-input", False),
    ("month", "text-input", True),
    ("average_grade", "number", False),
    ("attendance_count", "number", False),
    ("absence_count", "number", False),
    ("total_five", "number", False),
    ("total_four", "number", False),
    ("total_three", "number", False),
    ("total_two", "number", False),
    ("attendance_rate", "number", False),
    ("message_text", "paragraph", False),
)

WRAPPER = '''\n\n# Dify Code node entry point. The source above is embedded, not imported.\nTEMPLATE_NAME = "student_monthsly_send_v5"\n\ndef main(report, student_name="", recipient_name="", recipient_phone="", group_name="", month="", send_enabled="false"):\n    if str(send_enabled).strip().lower() != "true":\n        raise ValueError("AGRARIAN_SEND_ENABLED=false: no external HTTP request is allowed")\n    if isinstance(report, str):\n        report = json.loads(report)\n    if not isinstance(report, dict):\n        raise ValueError("report must be a JSON object")\n    for label, supplied, expected in (\n        ("student_name", student_name, report["student"]["full_name"]),\n        ("recipient_phone", recipient_phone, report["student"]["parent_phone"]),\n        ("month", month, report["period"]["month"]),\n    ):\n        if normalize(supplied) != normalize(expected):\n            raise ValueError(label + " differs from report")\n    expected_group = report.get("main_group", {}).get("name") or report["group"]["course_name"]\n    if normalize(group_name) != normalize(expected_group):\n        raise ValueError("group_name differs from report")\n    phone = "".join(char for char in normalize(recipient_phone) if char.isdigit())\n    if not 8 <= len(phone) <= 15:\n        raise ValueError("Invalid recipient_phone")\n    calculated = calculate(report)\n    rendered = render_meta(calculated)\n    whatsapp = {\n        "messaging_product": "whatsapp", "to": phone, "type": "template",\n        "template": {"name": TEMPLATE_NAME, "language": {"code": "ky_KG"},\n            "components": [{"type": "body", "parameters": [\n                {"type": "text", "text": value} for value in rendered["parameters"]\n            ]}]},\n    }\n    backend = {\n        "event": "student_monthly_report_result", "channel": "meta_whatsapp",\n        "report": report, "meta_request": whatsapp,\n        "rendered_text": rendered["preview"],\n    }\n    return {\n        "whatsapp_payload": json.dumps(whatsapp, ensure_ascii=False),\n        "backend_payload": json.dumps(backend, ensure_ascii=False),\n        **{"parameter_" + str(index): value for index, value in enumerate(rendered["parameters"], 1)},\n    }\n'''


def build(reference):
    graph = copy.deepcopy(reference)
    mapping = dict(zip(OLD_IDS, NEW_IDS))
    serialized = json.dumps(graph, ensure_ascii=False)
    for old, new in sorted(mapping.items(), key=lambda pair: -len(pair[0])):
        serialized = serialized.replace(old, new)
    graph = json.loads(serialized)
    nodes = {node["id"]: node for node in graph["nodes"]}
    if set(nodes) != set(NEW_IDS):
        raise ValueError("Unexpected reference graph nodes")

    nodes[START]["data"]["title"] = "Аграрный · входы backend"
    nodes[START]["data"]["variables"] = [
        {"variable": name, "label": name, "type": kind, "required": required, "max_length": 0}
        for name, kind, required in INPUTS
    ]

    source = SOURCE.read_text()
    if source.count("def main(report):") != 1:
        raise ValueError("Unexpected formatter entry point")
    code = source.replace("def main(report):", "def format_report(report):") + WRAPPER
    DEST_CODE.write_text(code)
    data = nodes[FORMAT]["data"]
    data["title"] = "Аграрный · gate и 24 параметра"
    data["code"] = code
    data["variables"] = [
        {"variable": name, "value_selector": [START, name], "value_type": "object" if name == "report" else "string"}
        for name in ("report", "student_name", "recipient_name", "recipient_phone", "group_name", "month")
    ] + [{"variable": "send_enabled", "value_selector": ["env", "AGRARIAN_SEND_ENABLED"], "value_type": "string"}]
    data["outputs"] = {name: {"type": "string", "children": None} for name in ("whatsapp_payload", "backend_payload", *(f"parameter_{i}" for i in range(1, 25)))}

    nodes[META]["data"].update({
        "title": "Meta · один запрос",
        "url": "{{#env.META_MESSAGES_URL#}}",
        "authorization": {"type": "api-key", "config": {"type": "bearer", "api_key": "{{#env.META_WHATSAPP_ACCESS_TOKEN#}}"}},
        "headers": "Content-Type:application/json",
        "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000},
        "error_strategy": None,
    })
    nodes[ONCE]["data"]["title"] = "Один запрос · без автоматического повтора"
    nodes[ITER]["data"]["title"] = "Один запрос · timeout даёт unknown"
    nodes[CAPTURE]["data"]["title"] = "Meta · сохранить ответ"
    nodes[UNWRAP]["data"]["title"] = "Meta · ответ или unknown"
    nodes[CLASSIFY]["data"]["title"] = "Meta · accepted/failed/unknown"
    nodes[CALLBACK]["data"].update({
        "title": "Backend · callback без повтора Meta",
        "url": "{{#env.BACKEND_REPORT_URL#}}",
        "authorization": {"type": "api-key", "config": {"type": "bearer", "api_key": "{{#env.BACKEND_REPORT_CALLBACK_TOKEN#}}"}},
        "headers": "Content-Type:application/json",
        "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000},
    })
    nodes[END]["data"]["title"] = "Результат провайдера и callback"
    nodes[END]["data"]["outputs"] = [
        {"variable": name, "value_selector": [CLASSIFY, name], "value_type": kind}
        for name, kind in (("provider_status", "string"), ("provider_message_id", "string"), ("provider_http_status", "number"), ("outcome_reason", "string"), ("backend_payload", "string"))
    ] + [{"variable": "callback_http_status", "value_selector": [CALLBACK, "status_code"], "value_type": "number"}]
    # No reference graph's application credentials or URLs are retained.
    for node in graph["nodes"]:
        if node["data"]["type"] == "http-request":
            assert node["data"]["retry_config"]["retry_enabled"] is False
    return graph


if __name__ == "__main__":
    reference = json.loads(Path(sys.argv[1]).read_text())
    graph = build(reference)
    DEST_GRAPH.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
    print(f"prepared {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
