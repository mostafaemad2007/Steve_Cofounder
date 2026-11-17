"""The six phase agents. Each has one job and one prompt file in prompts/<name>.md."""
from .base import Agent, OutputRejected, RunContext, StepResult
from .build import BuildAgent
from .commercial import CommercialAgent
from .discover import DiscoverAgent
from .launch import LaunchAgent
from .operate import OperateAgent
from .validate import ValidateAgent

AGENTS = (DiscoverAgent, ValidateAgent, BuildAgent, CommercialAgent, LaunchAgent, OperateAgent)

__all__ = ["AGENTS", "Agent", "OutputRejected", "RunContext", "StepResult", "DiscoverAgent",
           "ValidateAgent", "BuildAgent", "CommercialAgent", "LaunchAgent", "OperateAgent"]
