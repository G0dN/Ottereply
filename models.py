from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReplyJob:
    id: int
    tid: int
    fid: int
    job_type: str
    source_pid: Optional[int]
    source_authorid: Optional[int]
    source_subject: str
    source_message: Optional[str]
    reply_message: str
    bot_pid: Optional[int]
    parent_job_id: Optional[int]
    status: int
    retry_count: int
    last_error: Optional[str]
    created_at: int
    updated_at: int

    @classmethod
    def from_dict(cls, row: dict) -> "ReplyJob":
        return cls(
            id=row["id"],
            tid=row["tid"],
            fid=row["fid"],
            job_type=row.get("job_type", "reply"),
            source_pid=row.get("source_pid"),
            source_authorid=row.get("source_authorid"),
            source_subject=row.get("source_subject", ""),
            source_message=row.get("source_message"),
            reply_message=row["reply_message"],
            bot_pid=row.get("bot_pid"),
            parent_job_id=row.get("parent_job_id"),
            status=row["status"],
            retry_count=row.get("retry_count", 0),
            last_error=row.get("last_error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
