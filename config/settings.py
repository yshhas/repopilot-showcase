import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPO_ROOT = Path(
    os.getenv(
        "REPO_ROOT",
        str(PROJECT_ROOT),
    )
).resolve()

LOG_DIR = PROJECT_ROOT / "logs"
APP_LOG_FILE = LOG_DIR / "app.log"
AUDIT_LOG_FILE = LOG_DIR / "audit.jsonl"
BACKUP_STATE_FILE = LOG_DIR / "last_backup.json"

DATABASE_DIR = PROJECT_ROOT / "database"
TASK_DB_FILE = DATABASE_DIR / "tasks.db"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

APP_VERSION = "0.12.0"

AGENT_MODE = os.getenv("AGENT_MODE", "full").strip().lower()

API_DEFAULT_LIST_LIMIT = 20

API_MAX_LIST_LIMIT = 100

API_CONFIRM_TIMEOUT_SECONDS = int(
    os.getenv("API_CONFIRM_TIMEOUT_SECONDS", "300")
)

API_KEY = os.getenv("API_KEY", "").strip()

# ---- LLM Provider ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")).strip()

AUDIT_MAX_FIELD_LENGTH = 500

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "logs",
    "database",
    ".venv",
    "venv",
    "node_modules",
}

BLOCKED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

BLOCKED_FILE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}

REDACT_PLACEHOLDER = "[REDACTED]"

SENSITIVE_ASSIGNMENT_KEYS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "token",
    "private_key",
    "access_key",
)

SENSITIVE_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "PRIVATE_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
)

ALLOWED_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".js",
    ".ts",
    ".tsx",
    ".vue",
    ".html",
    ".css",
}

WRITABLE_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".js",
    ".ts",
    ".tsx",
    ".vue",
    ".html",
    ".css",
}

MAX_WRITE_BYTES = int(os.getenv("MAX_WRITE_BYTES", "100000"))
DEFAULT_WRITE_MAX_CHARS = MAX_WRITE_BYTES

PATCH_MAX_HUNKS = int(os.getenv("PATCH_MAX_HUNKS", "20"))

PATCH_MAX_CHANGED_LINES = int(os.getenv("PATCH_MAX_CHANGED_LINES", "500"))

PATCH_MAX_FILES = int(os.getenv("PATCH_MAX_FILES", "10"))

PATCH_PREVIEW_MAX_LINES = int(os.getenv("PATCH_PREVIEW_MAX_LINES", "40"))

PATCH_REQUIRE_BACKUP = os.getenv("PATCH_REQUIRE_BACKUP", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

DIFF_ENGINE_VERSION = "2"

INDEX_ENABLED = os.getenv("INDEX_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

INDEX_AUTO_REBUILD = os.getenv("INDEX_AUTO_REBUILD", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

INDEX_VERSION = int(os.getenv("INDEX_VERSION", "1"))

INDEX_DB_FILE = DATABASE_DIR / "repo_index.db"

CONTEXT_BUDGET_ENABLED = os.getenv("CONTEXT_BUDGET_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

CONTEXT_BUDGET_CHARS = int(os.getenv("CONTEXT_BUDGET_CHARS", "80000"))

CONTEXT_RANK_MAX_FILES = int(os.getenv("CONTEXT_RANK_MAX_FILES", "20"))

CHECKPOINT_ENABLED = os.getenv("CHECKPOINT_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

CHECKPOINT_MAX_PER_TASK = int(os.getenv("CHECKPOINT_MAX_PER_TASK", "5"))

CHECKPOINT_MAX_MEMORY_BYTES = int(os.getenv("CHECKPOINT_MAX_MEMORY_BYTES", "500000"))

CHECKPOINT_SCHEMA_VERSION = 2

# PR-M5-c: react_agent always writes mutation_state_json on save.
# When off, the flag no longer suppresses runtime v2 save — it remains for
# migration/rollback documentation only until M5-f removes it.
CHECKPOINT_MUTATION_STATE_V2_ENABLED = os.getenv(
    "CHECKPOINT_MUTATION_STATE_V2_ENABLED",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

TASK_SCOPED_BACKUP_ENABLED = os.getenv(
    "TASK_SCOPED_BACKUP_ENABLED",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

BACKUP_GLOBAL_DUAL_WRITE = os.getenv(
    "BACKUP_GLOBAL_DUAL_WRITE",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

TMS_RUNTIME_SOT_ENABLED = os.getenv(
    "TMS_RUNTIME_SOT_ENABLED",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

EXECUTION_STATE_DEDUP_ENABLED = os.getenv(
    "EXECUTION_STATE_DEDUP_ENABLED",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
}

# v0.10.1: default-on mutation workflow guard (set =0 to restore pre-0.10.1 behavior)
MUTATION_FSM_ENABLED = os.getenv("MUTATION_FSM_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# v0.10.1: default-on structured reject schema (set =0 to restore string-only rejects)
STRUCTURED_TOOL_REJECT_ENABLED = os.getenv(
    "STRUCTURED_TOOL_REJECT_ENABLED",
    "1",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

RAG_ENABLED = os.getenv("RAG_ENABLED", "0").strip().lower() not in {
    "0",
    "false",
    "no",
}

RAG_AUTO_REBUILD = os.getenv("RAG_AUTO_REBUILD", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

RAG_VERSION = int(os.getenv("RAG_VERSION", "1"))

RAG_VECTOR_DIR = DATABASE_DIR / "rag_vectors"

RAG_COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", "repo_code_chunks")

RAG_MAX_CHUNKS = int(os.getenv("RAG_MAX_CHUNKS", "5000"))

RAG_MAX_FILE_BYTES = int(os.getenv("RAG_MAX_FILE_BYTES", "204800"))

RAG_SEMANTIC_TOP_K = int(os.getenv("RAG_SEMANTIC_TOP_K", "10"))

RAG_EMBEDDING_DIM = int(os.getenv("RAG_EMBEDDING_DIM", "384"))

RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "mock-deterministic-v1")

RAG_HYBRID_ENABLED = os.getenv("RAG_HYBRID_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

RAG_CONTEXT_EXPAND = os.getenv("RAG_CONTEXT_EXPAND", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

DEFAULT_READ_MAX_CHARS = 20000
DEFAULT_LIST_MAX_RESULTS = 100
DEFAULT_SEARCH_MAX_RESULTS = 20

CONFIRM_REQUIRED_TOOLS = {
    "write_repo_file",
    "apply_patch",
}

REACT_MAX_STEPS = int(os.getenv("REACT_MAX_STEPS", "20"))

REACT_MAX_CONTEXT_CHARS = int(os.getenv("REACT_MAX_CONTEXT_CHARS", "40000"))
REACT_KEEP_RECENT_ROUNDS = int(os.getenv("REACT_KEEP_RECENT_ROUNDS", "10"))
# Token-level context trimming (v0.11+).
# Uses tiktoken's cl100k_base encoding (OpenAI standard) as an approximation.
# Note: This is an *estimate* — DeepSeek uses a different tokenizer, and actual
# token counts may differ. For exact billing, use the provider's own tokenizer.
# Set to 0 to disable token mode and fall back to REACT_MAX_CONTEXT_CHARS.
REACT_MAX_CONTEXT_TOKENS = int(os.getenv("REACT_MAX_CONTEXT_TOKENS", "0"))

TMS_ADAPTER_ENABLED = os.getenv("TMS_ADAPTER_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

PARITY_STRICT = os.getenv("PARITY_STRICT", "0").strip().lower() not in {
    "0",
    "false",
    "no",
}

MEMORY_STRUCTURED_TOOL_RESULT_ENABLED = os.getenv(
    "MEMORY_STRUCTURED_TOOL_RESULT_ENABLED",
    "0",
).strip().lower() not in {
    "0",
    "false",
    "no",
}

GIT_BACKUP_BRANCH_PREFIX = "agent-backup"
DEFAULT_BACKUP_MESSAGE = "agent backup before change"
