import io
import json

from knowitall_query import QueryService, serve_stdio


def test_stdio_adapter_emits_one_engineer_consumable_packet_per_request(published_graph, request_factory):
    store, generation = published_graph()
    request = request_factory()
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()

    serve_stdio(QueryService(store), input_stream, output_stream)

    packets = output_stream.getvalue().splitlines()
    assert len(packets) == 1
    response = json.loads(packets[0])
    assert response["status"] == "ok"
    assert response["resolved"]["snapshot_id"] == generation.snapshot.snapshot_id
    assert response["resolved"]["generation_id"] == generation.generation_id
    assert response["evidence"][0]["grade"] == "deterministic_extraction"


def test_stdio_adapter_isolates_malformed_lines_and_continues(published_graph, request_factory):
    store, _ = published_graph()
    valid = json.dumps(request_factory(request_id="valid-request"))
    input_stream = io.StringIO("not-json\n[]\n" + valid + "\n")
    output_stream = io.StringIO()

    serve_stdio(QueryService(store), input_stream, output_stream)

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert [response["status"] for response in responses] == ["invalid_request", "invalid_request", "ok"]
    assert responses[0]["request_id"] == "invalid"
    assert responses[1]["request_id"] == "invalid"
    assert responses[2]["request_id"] == "valid-request"
