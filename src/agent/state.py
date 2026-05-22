from typing import Optional, TypedDict


class PRReviewState(TypedDict):
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    pr_title: str
    pr_body: str
    head_sha: str
    pr_diff: Optional[str]
    diff_stats: Optional[dict]
    terraform_results: Optional[dict]
    analysis: Optional[str]
    comment_posted: bool
    error: Optional[str]
