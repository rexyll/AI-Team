"""Runtime package initialization."""

# Do not install workflow tracing here. Importing any ``runtime.*`` module
# executes this package initializer first, and eager workflow instrumentation
# imports ``runtime.workflow`` -> ``runtime.agent_router`` -> ``agents.base``.
# That creates a circular import when ``agents.base`` itself is the module that
# caused ``runtime`` to initialize.
#
# Workflow tracing is installed from ``runtime.workflow`` after TaskWorkflow
# has been fully defined, which preserves automatic instrumentation without
# introducing an import-time cycle.
