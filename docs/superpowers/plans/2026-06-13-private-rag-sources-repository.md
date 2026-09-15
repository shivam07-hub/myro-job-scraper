# Private RAG Sources Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and publish a private `shivam07-hub/rag-sources` repository with Git LFS, strict source provenance, sensitive-data safeguards, and one reviewed seed source for each pilot skill.

**Architecture:** The corpus is a standalone repository mounted at `Interview Prep/RAG Sources`. Binary originals are stored with Git LFS; plain-text manifests and validation code remain in Git. The parent Firecrawl repository references it as a submodule and ignores every other `Interview Prep` path.

**Tech Stack:** Git, GitHub private repositories, Git LFS, Python 3 standard library, `unittest`, PDF source files, Claude/Codex review workflow.

---

### Task 1: Create The Local Repository Skeleton

**Files:**
- Create: `Interview Prep/RAG Sources/README.md`
- Create: `Interview Prep/RAG Sources/AGENTS.md`
- Create: `Interview Prep/RAG Sources/.gitignore`
- Create: `Interview Prep/RAG Sources/.gitattributes`
- Create: `Interview Prep/RAG Sources/manifests/import-allowlist.txt`
- Create: `Interview Prep/RAG Sources/manifests/sources.jsonl`
- Create: `Interview Prep/RAG Sources/manifests/rejected-sources.jsonl`
- Create: `Interview Prep/RAG Sources/case-studies/drafts/README.md`
- Create: `Interview Prep/RAG Sources/case-studies/approved/README.md`

- [ ] **Step 1: Initialize the standalone repository**

Run:

```bash
mkdir -p "Interview Prep/RAG Sources"
git -C "Interview Prep/RAG Sources" init -b main
```

Expected: an empty Git repository with branch `main`.

- [ ] **Step 2: Add repository instructions and layout**

The repository instructions must state:

```text
- Repository visibility must remain private.
- Import only paths listed in manifests/import-allowlist.txt.
- Never import CVs, identity records, payroll records, signatures, photographs,
  personal correspondence, credentials, or private company records.
- Third-party originals stay private and are never exported as public assets.
- V1 content is authored and cross-reviewed through Claude/Codex sessions.
- Do not add cloud-LLM API keys or unattended LLM API integrations.
```

- [ ] **Step 3: Configure binary formats for Git LFS**

Add these patterns to `.gitattributes`:

```gitattributes
*.pdf filter=lfs diff=lfs merge=lfs -text
*.doc filter=lfs diff=lfs merge=lfs -text
*.docx filter=lfs diff=lfs merge=lfs -text
*.ppt filter=lfs diff=lfs merge=lfs -text
*.pptx filter=lfs diff=lfs merge=lfs -text
*.xls filter=lfs diff=lfs merge=lfs -text
*.xlsx filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.jpg filter=lfs diff=lfs merge=lfs -text
*.jpeg filter=lfs diff=lfs merge=lfs -text
*.zip filter=lfs diff=lfs merge=lfs -text
*.mp3 filter=lfs diff=lfs merge=lfs -text
*.mp4 filter=lfs diff=lfs merge=lfs -text
```

- [ ] **Step 4: Ignore reproducible and local artifacts**

Add:

```gitignore
derived/extracted-text/
derived/chunks/
derived/indexes/
.venv/
__pycache__/
*.pyc
.DS_Store
```

### Task 2: Add Corpus Validation With TDD

**Files:**
- Create: `Interview Prep/RAG Sources/scripts/validate_corpus.py`
- Create: `Interview Prep/RAG Sources/tests/test_validate_corpus.py`

- [ ] **Step 1: Write failing unit tests**

Tests must cover:

```python
def test_valid_manifest_passes(): ...
def test_duplicate_source_id_fails(): ...
def test_missing_file_fails(): ...
def test_checksum_mismatch_fails(): ...
def test_source_must_be_allowlisted(): ...
def test_sensitive_import_path_fails(): ...
def test_binary_extension_requires_lfs_rule(): ...
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd "Interview Prep/RAG Sources"
python3 -m unittest discover -s tests -v
```

Expected: import failure because `scripts.validate_corpus` does not exist.

- [ ] **Step 3: Implement the validator**

`validate_corpus.py` must:

```python
REQUIRED_FIELDS = {
    "source_id", "path", "title", "publisher", "source_url",
    "retrieved_at", "sha256", "mime_type", "bytes", "skills",
    "topics", "authority_tier", "rights", "redistributable",
    "review_status", "imported_from",
}
SENSITIVE_TOKENS = {
    "passport", "pan card", "payslip", "signature", "cheque",
    "joining letter", "personal cv", "formal picture", "uan",
}
```

It must parse JSONL, require unique IDs, require each source file and allowlist
entry, compare SHA-256 and byte size, reject sensitive path tokens, and verify
that every binary suffix has a matching `.gitattributes` LFS pattern. It exits
nonzero and prints all errors when validation fails.

- [ ] **Step 4: Run tests and confirm success**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all seven tests pass.

### Task 3: Install And Configure Repository-Local Git LFS

**Files:**
- Create locally: `.tools/bin/git-lfs`
- Modify locally: `Interview Prep/RAG Sources/.git/config`

- [ ] **Step 1: Download the official macOS arm64 Git LFS release**

Resolve the latest release from the official `git-lfs/git-lfs` GitHub API,
download its Darwin arm64 archive under `.tools/`, verify the archive is
non-empty, and extract the executable to `.tools/bin/git-lfs`.

- [ ] **Step 2: Configure LFS only for the new repository**

Run:

```bash
PATH="/Users/incognito/firecrawl_Supabase/.tools/bin:$PATH" \
  git -C "Interview Prep/RAG Sources" lfs install --local
```

Expected: Git LFS hooks are installed only in the standalone repository.

- [ ] **Step 3: Verify attribute routing**

Run:

```bash
git -C "Interview Prep/RAG Sources" check-attr filter -- sample.pdf
```

Expected:

```text
sample.pdf: filter: lfs
```

### Task 4: Import One Reviewed Seed Per Pilot Skill

**Files:**
- Create: `Interview Prep/RAG Sources/sources/management-consulting/iim-lucknow-casebook-2022.pdf`
- Create: `Interview Prep/RAG Sources/sources/product-strategy/iim-lucknow-prodman-analytics-guide-2022.pdf`
- Create: `Interview Prep/RAG Sources/sources/financial-accounting/ind-as-2-inventories-2019.pdf`
- Create: `Interview Prep/RAG Sources/sources/machine-learning/multiple-regression-course-notes.pdf`
- Modify: `Interview Prep/RAG Sources/manifests/import-allowlist.txt`
- Modify: `Interview Prep/RAG Sources/manifests/sources.jsonl`

- [ ] **Step 1: Visually and textually inspect the four PDFs**

Use the PDF workflow to verify title pages, publishers, page counts, and that
the files do not contain personal records. Record that the regression document
is a narrow statistical-modeling seed, not comprehensive ML coverage.

- [ ] **Step 2: Add exact source paths to the allowlist**

Allow only:

```text
Disha Consulting/Casebooks/IIM Lucknow Casebook 2022.pdf
Disha PM/IIM Lucknow's ProdMan and Analytics Guide 2022.pdf
One Drive Files/Study Material/2nd Term/MANAC/Pre Mid/11-10-20222-Session-3-Material Cost Control/IndAS2_2019.pdf
One Drive Files/Study Material/2nd Term/QAM2/PostMid/Multiple Regression.pdf
```

- [ ] **Step 3: Copy the four approved files**

Copy each source to the canonical destination listed above. Do not copy any
directory recursively.

- [ ] **Step 4: Add provenance records**

Each JSONL record must contain the exact checksum and byte size, one canonical
skill, topic tags, authority tier, rights classification, `redistributable:
false`, `review_status: "approved_private"`, and its allowlisted source path.

- [ ] **Step 5: Run corpus validation**

Run:

```bash
cd "Interview Prep/RAG Sources"
python3 scripts/validate_corpus.py
python3 -m unittest discover -s tests -v
```

Expected: validation succeeds and all tests pass.

### Task 5: Commit The Standalone Repository

**Files:**
- Stage only files under `Interview Prep/RAG Sources`

- [ ] **Step 1: Confirm LFS pointers are staged**

Run:

```bash
PATH="/Users/incognito/firecrawl_Supabase/.tools/bin:$PATH" git lfs status
git diff --cached --check
```

Expected: all four PDFs are listed as LFS objects and no whitespace errors are
reported.

- [ ] **Step 2: Commit the initial corpus**

Run:

```bash
git add .
git commit -m "feat: initialize private rag source corpus"
```

Expected: one root commit containing scaffolding, validation, manifests, and
four LFS pointer files.

### Task 6: Create And Push The Private GitHub Repository

**Remote:** `shivam07-hub/rag-sources`

- [ ] **Step 1: Create the GitHub repository**

Use the authenticated GitHub web session to create `shivam07-hub/rag-sources`
with visibility **Private**, no generated README, and no license.

- [ ] **Step 2: Add the SSH remote**

Run:

```bash
git remote add origin git@github.com:shivam07-hub/rag-sources.git
```

- [ ] **Step 3: Push Git and LFS objects**

Run:

```bash
PATH="/Users/incognito/firecrawl_Supabase/.tools/bin:$PATH" git push -u origin main
```

Expected: the main branch and four LFS objects upload successfully.

- [ ] **Step 4: Verify privacy and remote contents**

Confirm through GitHub that repository visibility is private and that source
files appear as LFS-backed objects.

### Task 7: Link The Private Repository Into Firecrawl

**Files:**
- Modify: `.gitignore`
- Create: `.gitmodules`
- Create gitlink: `Interview Prep/RAG Sources`

- [ ] **Step 1: Ignore the legacy archive while allowing the submodule**

Append:

```gitignore
/Interview Prep/*
!/Interview Prep/RAG Sources
```

- [ ] **Step 2: Register the existing checkout as a submodule**

Use the private SSH remote and the existing local checkout so no legacy archive
content is staged.

- [ ] **Step 3: Verify parent staging**

Run:

```bash
git status --short
git diff --cached --name-status -- .gitignore .gitmodules "Interview Prep/RAG Sources"
```

Expected: only `.gitignore`, `.gitmodules`, and the gitlink are part of this
task; existing unrelated staged and unstaged changes remain untouched.

- [ ] **Step 4: Commit only the parent linkage**

Run:

```bash
git commit --only .gitignore .gitmodules "Interview Prep/RAG Sources" \
  -m "chore: link private rag sources repository"
```

### Task 8: Final Verification

- [ ] **Step 1: Re-run standalone checks**

```bash
cd "Interview Prep/RAG Sources"
python3 scripts/validate_corpus.py
python3 -m unittest discover -s tests -v
PATH="/Users/incognito/firecrawl_Supabase/.tools/bin:$PATH" git lfs status
git status --short
```

Expected: validator and tests pass; LFS and repository working trees are clean.

- [ ] **Step 2: Verify parent submodule**

```bash
cd /Users/incognito/firecrawl_Supabase
git submodule status -- "Interview Prep/RAG Sources"
git show --stat --oneline HEAD
```

Expected: the submodule points to the pushed `rag-sources` commit and the parent
commit contains only the linkage files.
