"""Runtime package initialization and cross-cutting runtime instrumentation."""

from runtime.workflow_root_tracing import install_workflow_root_tracing

install_workflow_root_tracing()
