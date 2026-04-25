"""Experiment helpers for single-run and batch experiment packaging."""


def run_batch_experiments(*args, **kwargs):
    from .batch_runner import run_batch_experiments as _run_batch_experiments

    return _run_batch_experiments(*args, **kwargs)


def run_monte_carlo_experiments(*args, **kwargs):
    from .monte_carlo import run_monte_carlo_experiments as _run_monte_carlo_experiments

    return _run_monte_carlo_experiments(*args, **kwargs)


def prepare_experiment_context(*args, **kwargs):
    from .runner import prepare_experiment_context as _prepare_experiment_context

    return _prepare_experiment_context(*args, **kwargs)


def run_experiment(*args, **kwargs):
    from .runner import run_experiment as _run_experiment

    return _run_experiment(*args, **kwargs)


def run_experiment_with_model(*args, **kwargs):
    from .runner import run_experiment_with_model as _run_experiment_with_model

    return _run_experiment_with_model(*args, **kwargs)


def run_sensitivity_analysis(*args, **kwargs):
    from .sensitivity_runner import run_sensitivity_analysis as _run_sensitivity_analysis

    return _run_sensitivity_analysis(*args, **kwargs)


def __getattr__(name):
    if name == "DEFAULT_POLICY_PROFILES":
        from .runner import DEFAULT_POLICY_PROFILES as _default_policy_profiles

        return _default_policy_profiles
    if name == "DEFAULT_SENSITIVITY_PARAMETER_GRID":
        from .sensitivity_runner import DEFAULT_SENSITIVITY_PARAMETER_GRID as _default_sensitivity_parameter_grid

        return _default_sensitivity_parameter_grid
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DEFAULT_POLICY_PROFILES",
    "DEFAULT_SENSITIVITY_PARAMETER_GRID",
    "prepare_experiment_context",
    "run_batch_experiments",
    "run_monte_carlo_experiments",
    "run_experiment",
    "run_experiment_with_model",
    "run_sensitivity_analysis",
]
