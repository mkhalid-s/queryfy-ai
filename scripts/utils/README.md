# Utility Scripts

Common Bash patterns extracted from heavy usage (70,685 Bash calls across 2,095 sessions).
These scripts replace repeated ad-hoc commands with structured, reusable tools.

## Available Scripts

### 1. Find Unused Imports
**Script:** `find-unused-imports.sh`
**Purpose:** Scan for unused Python imports

```bash
./scripts/utils/find-unused-imports.sh              # Scan backend/app
./scripts/utils/find-unused-imports.sh backend/     # Scan specific dir
```

**Output:**
```
❌ backend/app/services/tools.py
   Unused: datetime
❌ backend/app/api/chat.py
   Unused: Optional
```

**Auto-fix:**
```bash
ruff check --select F401 --fix backend/
```

**Replaces:** Multiple `grep "^import\|^from" | grep -v` commands

---

### 2. Find Dead Code
**Script:** `find-dead-code.sh`
**Purpose:** Find unreferenced functions and classes

```bash
./scripts/utils/find-dead-code.sh              # Scan backend/app
./scripts/utils/find-dead-code.sh backend/     # Scan specific dir
```

**Output:**
```
## Unreferenced Functions
❌ backend/app/utils/helpers.py:45
   Function: old_helper (0 references)

## Unreferenced Classes
❌ backend/app/models/deprecated.py:12
   Class: LegacyModel (0 references)
```

**Note:** Manual review recommended - some may be entry points or dynamically imported

**Replaces:** Nested `grep -rn "^def\|^class" | while read; do grep -r` loops

---

### 3. Find Empty Files
**Script:** `find-empty-files.sh`
**Purpose:** Find empty or near-empty files for cleanup

```bash
./scripts/utils/find-empty-files.sh
```

**Output:**
```
## Completely Empty Files
./backend/app/utils/placeholder.py

## Empty __init__.py Files
./backend/app/services/__init__.py
./frontend/src/components/deprecated/__init__.py

## Files with Only Comments
./backend/app/models/old.py
```

**Common action:** Delete empty files, add namespace exports to `__init__.py`

**Replaces:** Multiple `find . -empty` and `find . -exec grep` commands

---

### 4. Check Config Consistency
**Script:** `check-config-consistency.sh`
**Purpose:** Validate configuration across environment files

```bash
./scripts/utils/check-config-consistency.sh
```

**Checks:**
1. `.env.example` vs `.env.production.example` key differences
2. Hardcoded secrets in docker-compose files
3. Unused environment variables

**Output:**
```
## Comparing .env.example vs .env.production.example

### Keys only in .env.example:
DEBUG_MODE

### Keys only in .env.production.example:
SENTRY_DSN

## Scanning for potential secrets
⚠️  docker-compose.yml:
   - POSTGRES_PASSWORD=changeme

## Unused Environment Variables
❌ LEGACY_API_KEY (not found in code)
```

**Replaces:** Multiple `grep -E "KEY|SECRET|PASSWORD"` and `comm` commands

---

### 5. Validate All
**Script:** `validate-all.sh`
**Purpose:** Run all validation checks (lint, type check, tests)

```bash
./scripts/utils/validate-all.sh
```

**Runs:**
- **Backend:** ruff check, mypy, pytest
- **Frontend:** npm run lint, npm run build

**Output:**
```
## Backend Validation
→ Ruff (linting)...
  ✓ Passed
→ MyPy (type checking)...
  ✓ Passed
→ Pytest (tests)...
  ✓ Passed

## Frontend Validation
→ ESLint (linting)...
  ✓ Passed
→ Build check...
  ✓ Passed

✓ All validations passed!
```

**Exit codes:**
- `0` = All passed
- `1` = At least one failed

**Use in CI:**
```bash
./scripts/utils/validate-all.sh || exit 1
```

**Replaces:** Manually running `cd backend && ruff && mypy && pytest && cd ../frontend && npm run lint && npm run build`

---

## Integration with Claude Code

### Use Before /cleanup
Run discovery scripts to identify cleanup candidates:

```bash
./scripts/utils/find-unused-imports.sh > imports-report.txt
./scripts/utils/find-dead-code.sh > dead-code-report.txt
./scripts/utils/find-empty-files.sh > empty-files-report.txt
```

Then use `/cleanup` skill with the reports as context.

### Use in Pre-commit Hook
```bash
# .git/hooks/pre-commit
#!/bin/bash
./scripts/utils/validate-all.sh || {
    echo "Validation failed - fix issues or use --no-verify"
    exit 1
}
```

### Use in Claude Prompts
```
Check for unused imports using ./scripts/utils/find-unused-imports.sh
and create a cleanup plan based on the output.
```

---

## Performance

Each script is optimized for speed:
- Uses `find` instead of `ls -R` for file discovery
- Streams results (no temporary files)
- Parallel processing where possible
- Excludes common ignore paths (node_modules, .git, venv)

**Typical execution times:**
- find-unused-imports: 2-5 seconds
- find-dead-code: 5-10 seconds
- find-empty-files: 1-2 seconds
- check-config-consistency: 1-3 seconds
- validate-all: 30-60 seconds (depends on test suite)

---

## Customization

All scripts accept directory arguments:

```bash
# Scan specific directory
./scripts/utils/find-unused-imports.sh backend/app/services

# Scan multiple times
for dir in backend/app backend/tests; do
    ./scripts/utils/find-dead-code.sh "$dir"
done
```

---

## Troubleshooting

**"Permission denied"**
```bash
chmod +x scripts/utils/*.sh
```

**"No such file or directory"**
- Run from project root
- Check file exists: `ls scripts/utils/`

**"command not found: ruff"**
```bash
pip install ruff mypy pytest
```

**Scripts too slow**
- Add more exclusions to find commands
- Use `--exclude-dir` flags
- Limit depth: `find . -maxdepth 3`

---

## Contributing

When you notice a repeated Bash pattern:
1. Extract it to a new script in `scripts/utils/`
2. Add documentation here
3. Update `CLAUDE.md` quick reference
4. Make it executable: `chmod +x scripts/utils/new-script.sh`

**Pattern examples:**
- File discovery loops
- Nested grep operations
- Config validation checks
- Test runners
- Git operations

These scripts save ~500-1000 Bash tool calls per week!
