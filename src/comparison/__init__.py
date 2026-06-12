"""comparison - head-to-head evaluator across pipelines.

Its job is to:

  1. run several pipelines on the same test split
  2. produce per-window PipelinePrediction rows in a unified shape
  3. stratify metrics by scenario_family / service / window_type
  4. build score-level ensembles
  5. attach paired-bootstrap 95% CIs to every reported number

The package owns NO modelling code - it only orchestrates and reports.
"""

from .schema import PipelinePrediction, PipelineResult
from .pipelines import PipelineRunner
from .ensemble import EnsemblePipeline, blend_mean, blend_max, blend_weighted
from .stratified import stratified_metrics
from .significance import paired_bootstrap_ci

__all__ = [
    "PipelinePrediction",
    "PipelineResult",
    "PipelineRunner",
    "EnsemblePipeline",
    "blend_mean",
    "blend_max",
    "blend_weighted",
    "stratified_metrics",
    "paired_bootstrap_ci",
]
__version__ = "0.1.0"
