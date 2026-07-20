# chunk_types.py
from dataclasses import dataclass, asdict
from typing import Literal, Optional

ChunkKind = Literal["pdf_page", "transcript_turn", "text"]

@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str          # stable, e.g. "a1b2-0003" — not a list index
    text: str
    kind: ChunkKind

    page: Optional[int] = None                # pdf_page only
    speaker: Optional[str] = None              # transcript_turn only
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    char_start: Optional[int] = None           # text only
    char_end: Optional[int] = None

    def __post_init__(self):
        if self.kind == "pdf_page" and self.page is None:
            raise ValueError("pdf_page chunk requires 'page'")
        if self.kind == "transcript_turn" and None in (self.speaker, self.t_start, self.t_end):
            raise ValueError("transcript_turn chunk requires speaker, t_start, t_end")
        if self.kind == "text" and None in (self.char_start, self.char_end):
            raise ValueError("text chunk requires char_start, char_end")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**d)