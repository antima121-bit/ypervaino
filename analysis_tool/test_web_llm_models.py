from web.llm_models import list_unique_api_models, resolve_model_name


def test_unique_api_models():
    models = list_unique_api_models()
    assert "gpt-5.6-luna" in models
    assert len(models) == len(set(models))


def test_resolve_model_name_default_pair():
    assert resolve_model_name("gpt-5.6-luna", "high") == "luna_high"
