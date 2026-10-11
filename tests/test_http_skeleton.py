from nl2service.agent.main_agent import MainLLMAgent, RefinedRender
from nl2service.agent.session import MainAgentSessionState
from nl2service.render.renderer import ServiceRenderer


def test_http_business_refinement_preserves_framework_entrypoint(monkeypatch, http_spec):
    original = ServiceRenderer().render_tree(http_spec)
    changed = original["handler/http_handler.go"].replace('thttp.HandleFunc("/events", h.Events)', 'http.HandleFunc("/events", nil)')
    changed = changed.replace("writeJSON(w, http.StatusOK, nil)", 'writeJSON(w, http.StatusOK, map[string]string{"result": "implemented"})')
    monkeypatch.setattr(MainLLMAgent, "_invoke_structured", lambda self, **kwargs: (
        "fake", RefinedRender(files={"main.go": "broken entrypoint", "handler/http_handler.go": changed})))
    result = MainLLMAgent().refine_code(MainAgentSessionState(user_request="Implement events", draft_spec=http_spec, rendered_files=original))
    assert result.files["main.go"] == original["main.go"]
    assert 'thttp.HandleFunc("/events", h.Events)' in result.files["handler/http_handler.go"]
    assert '"implemented"' in result.files["handler/http_handler.go"]


def test_register_span_ignores_braces_in_comments_and_strings():
    source = 'func (h *HTTPHandler) Register() {\n// }\nprintln("}")\n}\nfunc other() {}'
    span = MainLLMAgent._register_span(source)
    assert source[span[0]:span[1]].endswith('println("}")\n}')
