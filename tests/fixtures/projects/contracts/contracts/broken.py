"""A contract module that fails as it is imported."""

msg = "database not configured"
raise RuntimeError(msg)
