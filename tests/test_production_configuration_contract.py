from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
PRODUCTION = ROOT / "docs" / "production_configuration.md"
SETUP = ROOT / "docs" / "setup.md"
CONFIG_MODEL = ROOT / "config" / "model.py"

# Import name used inside config/model.py -> distribution name in requirements.txt.
_PROVIDER_IMPORTS = {
    "openai": "openai",
    "dotenv": "python_dotenv",
}


def _declared_pins() -> dict[str, str]:
    """Return {distribution name: pinned version} from requirements.txt."""
    pins: dict[str, str] = {}
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        assert separator, f"requirements entries must be exactly pinned: {line!r}"
        pins[name.strip().lower().replace("-", "_")] = version.strip()
    return pins


def test_requirements_declare_provider_chain_dependencies() -> None:
    pins = _declared_pins()

    assert "openai" in pins
    assert "python_dotenv" in pins


def test_every_config_model_import_is_declared() -> None:
    content = CONFIG_MODEL.read_text(encoding="utf-8-sig")
    pins = _declared_pins()

    for import_name, distribution_name in _PROVIDER_IMPORTS.items():
        assert f"from {import_name} import" in content, (
            f"config/model.py is expected to import {import_name}; "
            "update this contract when the provider imports change"
        )
        assert distribution_name in pins, (
            f"{distribution_name} must stay pinned in requirements.txt "
            "because config/model.py imports it at module level"
        )


def test_production_checklist_documents_provider_and_runtime_contract() -> None:
    assert PRODUCTION.is_file()
    content = PRODUCTION.read_text(encoding="utf-8-sig")

    for token in (
        "# AI-Team Production Configuration Checklist",
        "Python 3.14",
        "pip install -r requirements.txt",
        # 多 Provider 注册表：两个 profile 的凭据变量均须在案。
        "AGNES_API_KEY",
        "OPENROUTER_API_KEY",
        "DEFAULT_PROVIDER",
        # 角色绑定与 Ox Alpha 初始模型。
        "{ROLE}_MODEL",
        "PLANNER_MODEL",
        "stealth/ox-alpha",
        # 惰性解析语义（9.3 引入，9.6 起按 profile 解析）。
        "Lazy provider resolution",
        "config.get_client_for(profile)",
        "MockLLM",
        "DEFAULT_SANDBOX",
        "os.replace()",
        "deny-by-default",
    ):
        assert token in content, f"production checklist must document: {token}"


def test_setup_guide_states_real_dependency_contract() -> None:
    content = SETUP.read_text(encoding="utf-8-sig")

    assert "pip install -r requirements.txt" in content
    # The historical claim that requirements.txt stays empty is obsolete.
    assert "keeps `requirements.txt` empty" not in content
