"""Post-process synthetic Jira shadow issues to look human-written.

Strips lab-only metadata from description / comments / labels so the
Jira memory corpus passes corporate smell-test. Keeps the
telemetry_links sibling intact for retrieval ground truth.
"""
