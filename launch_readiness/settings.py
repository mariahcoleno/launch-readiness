"""Settings that a program manager might want to change."""

# New gates are due this many days before the launch's target date,
# so they are done before the go/no-go review rather than on launch day.
GATE_DUE_DAYS_BEFORE_LAUNCH = 7

# A gate that hasn't started and is due within this many days (today included)
# is flagged "at risk".
GATE_AT_RISK_DAYS = 3

# --- AI status summary (feature 7) ---
# Used only when ANTHROPIC_API_KEY is set. The AI drafts text for a person to
# review; it never changes gates or records decisions.
AI_SUMMARY_MODEL = "claude-opus-5-5"
AI_SUMMARY_EFFORT = "medium"          # low | medium | high | xhigh | max
AI_SUMMARY_TIMEOUT_SECONDS = 120
