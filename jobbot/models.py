from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    """One job posting, normalised across all sources."""

    source: str     # "greenhouse" | "lever" | "comeet"
    company: str
    job_id: str     # unique within the source
    title: str
    location: str
    url: str

    @property
    def key(self) -> str:
        """Stable id used to remember which jobs were already sent."""
        return f"{self.source}:{self.company}:{self.job_id}"
