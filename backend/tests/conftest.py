import os

# Set before any app.* import happens in test collection: app.config.Settings
# requires these at construction time by design (fail-fast in real deploys).
# Tests use obviously-fake values and never hit a real network.
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
os.environ.setdefault("CLICKHOUSE_PASSWORD", "test-password")
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
