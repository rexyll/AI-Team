# Configuration Reference

AI-Team configuration is environment-driven. Use `config.configuration.load_configuration()` as the validated configuration boundary before constructing runtime LLM clients.

## Provider and model resolution

The effective role configuration follows this precedence:

1. role-specific provider/model (`<ROLE>_PROVIDER`, `<ROLE>_MODEL`)
2. shared provider/model defaults (`DEFAULT_PROVIDER`, `DEFAULT_MODEL`)
3. provider model fallback where supported by the existing provider configuration

For Developer instances, instance-specific settings (`DEVELOPER_<N>_PROVIDER`, `DEVELOPER_<N>_MODEL`) take precedence over the shared Developer settings and shared defaults.

## Provider credentials

Credentials and endpoints remain environment variables and must not be committed. `.env` is for local development and is ignored by git.

A minimal provider configuration follows the provider-specific variables documented in `docs/production_configuration.md`.

## Validation

`load_configuration()` validates provider/model references and Developer instance configuration before runtime use. Invalid provider names, missing required provider configuration, unsupported models, and invalid Developer counts should fail fast with a `ConfigurationError` rather than reaching an unrelated execution stage.

Configuration validation does not make a network request. Credential validity against the remote provider is checked when the provider client is actually used.

## CLI interaction

The CLI reads the same environment-driven configuration contract as the runtime. The CLI's `--projects-base`, `--dashboard`, and `--output` options control execution/output behavior; they do not bypass model configuration validation.

See `docs/cli_reference.md` for command syntax and `docs/plugin_api.md` for extension configuration boundaries.
