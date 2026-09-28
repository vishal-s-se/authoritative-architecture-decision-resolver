# Stakeholder Validation

Use the Ask AI feedback form after reviewing an answer. Rate each question
from 1 to 5 and add a comment:

- Was the answer clear?
- Was the source clear?
- Was the citation useful?
- Did the result increase trust?
- Would you use this instead of manual checking?

The live summary is available at `GET /api/feedback/summary`, including
response count, averages, and the percentage of ratings at least 4. The
Evaluation page reads this same feedback table so the stakeholder summary is
always pulled from recorded responses rather than hand-entered numbers.

## Summary

Run the feedback summary endpoint and record the date, respondents, averages,
and percentage agreeing (rating >= 4) here.