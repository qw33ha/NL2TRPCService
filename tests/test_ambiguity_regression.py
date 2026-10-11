from nl2service.agent.ambiguity import AmbiguityAnalyzer, AmbiguityItem, AmbiguityReview


def test_disabled_deployment_and_answered_fields_do_not_block(http_spec):
    review = AmbiguityReview(items=[
        AmbiguityItem(key=field, field=field, question="Choose?", reason="Uncertain", impact="deployment", priority="important")
        for field in ["exposure.type", "deploy.enabled", "service.name"]
    ])

    class Provider:
        def get_model(self, name):
            return self

        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            return review

    result = AmbiguityAnalyzer(Provider()).analyze(
        "Deployment undecided", http_spec,
        [{"field": "deploy.enabled", "question": "Deploy?", "answer": "False"}], [],
    )
    assert [item.field for item in result.items] == ["service.name"]
