"""Messages between the pipeline and whatever drives it: the web UI, the command line, or a test.

The pipeline is a generator. It yields Say (information for the founder) and Request (something only
the founder can decide), receives a Reply for every Request, and finally returns Done.
"""
from dataclasses import dataclass, field

#: confirm  - is this step right? approve, or reject with changes (empty rejection stops the run)
#: gate     - a gate passed, or recommends pivot; the founder decides whether to go on
#: publish / send / spend - an outward action; nothing happens without approval (and it is MOCKED)
#: question - the founder types an answer (for example the target market)
REQUEST_KINDS = ("confirm", "gate", "publish", "send", "spend", "question")


@dataclass
class Say:
    text: str
    files: list[str] = field(default_factory=list)
    kind: str = "info"            # info | phase | step | gate | notice | refusal | done
    phase: int | None = None
    outcome: str | None = None    # for kind == "gate": go / repeat / pivot / stop
    data: dict = field(default_factory=dict)   # for gates: the numbers used and what would change


@dataclass
class Request:
    step_id: str
    kind: str
    prompt: str
    files: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in REQUEST_KINDS:
            raise ValueError(f"kind must be one of {REQUEST_KINDS}")

    @property
    def needs_text(self) -> bool:
        return self.kind == "question"


@dataclass
class Reply:
    approve: bool | None = None   # None for an answer to a question
    text: str = ""


@dataclass
class Done:
    #: completed | stopped | refused | stopped_by_founder | error
    outcome: str
    summary: str
    files: list[str] = field(default_factory=list)
    last_gate: str | None = None
