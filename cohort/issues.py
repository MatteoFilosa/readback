from dataclasses import asdict, dataclass

ERROR, WARNING, ASSUMPTION = "error", "warning", "assumption"


@dataclass
class Issue:
    check: str
    level: str
    message: str
    clause: int | None = None
    attr: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)
