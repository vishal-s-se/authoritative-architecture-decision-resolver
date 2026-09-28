# Decision Log

This log evaluates the failing evaluation scenarios against the stated requirements to determine if the ground truth or the resolver is at fault.

## Failing Scenarios

### 1. older_board_vs_newer_developer
* **Failure:** Ground truth expected the older version (approved by Architecture Board), but the resolver selected the newer version (approved by Developer).
* **Verdict:** The **resolver** is wrong.
* **Reasoning:** The requirement states that "two approved versions with different owner authority -> higher authority wins unless overridden". The Architecture Board has higher authority than Developer, so the older version should win. The weighted heuristic incorrectly allowed the recency/version number weights to overpower the ownership weight.

### 2. equal_recency_approver_authority
* **Failure:** Ground truth expected the version with the higher authority approver, but the resolver selected the lower authority version.
* **Verdict:** The **resolver** is wrong.
* **Reasoning:** Following the requirement "two approved versions with different owner authority -> higher authority wins unless overridden", the version approved by the higher authority must be selected when all other factors (like recency) are equal. The resolver failed to properly prioritize the approver's authority level.

### 3. ancient_vs_new_conflicting_rejection
* **Failure:** Ground truth expected the query to flag a conflict (`MANUAL_REVIEW_REQUIRED`), but the resolver returned an answer.
* **Verdict:** The **resolver** is wrong.
* **Reasoning:** A newer conflicting rejection on an ancient approval represents a material conflict. The resolver should have detected the conflict and suspended automatic resolution.

### 4. revoked_newest_approval
* **Failure:** Ground truth expected the older approved version, but the resolver selected the newer version whose approval was revoked.
* **Verdict:** The **resolver** is wrong.
* **Reasoning:** If an approval is revoked, that version is no longer eligible to win unless it has another valid approval. A newer draft or unapproved version never overrides an approved version. The resolver incorrectly selected it, likely not properly enforcing eligibility.

### 5. override_removed_reresolved
* **Failure:** Ground truth expected the older board-approved version to win, but the resolver selected the newer developer-approved version.
* **Verdict:** The **resolver** is wrong.
* **Reasoning:** Once an override is removed, the resolution must fall back to the native logic. Under native logic, "higher authority wins unless overridden". The board-approved version must beat the developer-approved version. The resolver is incorrectly choosing the developer version.
