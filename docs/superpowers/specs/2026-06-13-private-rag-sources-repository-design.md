# Private RAG Sources Repository Design

**Date:** 2026-06-13

**Status:** Approved for specification

## Goal

Create a standalone private GitHub repository named `rag-sources` that holds the
authoritative source corpus for interview-preparation pages, question-bank
generation, and original case-study development.

The repository will live locally at:

```text
/Users/incognito/firecrawl_Supabase/Interview Prep/RAG Sources/
```

The source corpus remains private. Public product pages, normalized questions,
and rewritten case studies may cite the corpus, but must not expose private
files or republish third-party documents.

## Boundaries

- All setup work stays under `/Users/incognito/firecrawl_Supabase/`.
- The new repository is private on GitHub.
- V1 uses Claude and Codex interactively for corpus review, drafting, and
  cross-review. LM Studio is not required for V1.
- V1 does not add Anthropic, OpenAI, or other cloud-LLM API integrations or API
  keys to either repository. Agent sessions operate only on explicitly
  approved source files.
- Firecrawl Cloud may discover and capture authoritative public sources while
  the remaining subscription credits are available.
- Existing material under `Interview Prep/` is not imported wholesale.
- Imports use an explicit allowlist and a sensitive-data screening pass.
- CVs, identity documents, payslips, photographs, signatures, joining
  documents, personal correspondence, and similar records are always excluded.
- Third-party books, casebooks, course packs, and standards remain private and
  are never published as downloadable assets.

## Repository Layout

```text
rag-sources/
  README.md
  AGENTS.md
  .gitignore
  .gitattributes
  sources/
    machine-learning/
    product-strategy/
    management-consulting/
    financial-accounting/
  manifests/
    sources.jsonl
    import-allowlist.txt
    rejected-sources.jsonl
  derived/
    extracted-text/
    chunks/
    indexes/
  case-studies/
    drafts/
    approved/
  scripts/
  tests/
```

`sources/` contains approved original files and web captures. `derived/`
contains reproducible local extraction products. `case-studies/approved/`
contains original material cleared for public use; it does not contain copied
source prose.

## Source Manifest

Every approved source has one JSONL record containing:

- Stable `source_id`
- Local relative path
- Canonical source URL, when applicable
- Publisher or institution
- Document title
- Retrieval date
- SHA-256 checksum
- MIME type and byte size
- Skill and topic tags
- Authority tier
- Copyright or license classification
- Public redistribution permission
- Extraction status
- Notes and review status

Authority tiers:

1. Standards bodies, regulators, official documentation, and peer-reviewed
   publications
2. Universities, recognized professional institutions, and established
   textbooks or course material
3. Established employers, consulting firms, and respected practitioner
   publications
4. Community-authored interview guides and casebooks

Question generation should prefer higher tiers. Tier 4 material may contribute
formats or scenarios, but factual claims require support from a higher-tier
source.

## Import Workflow

1. Add a candidate path or URL to the allowlist.
2. Scan filenames and extracted text for personal data and credentials.
3. Check file type, size, checksum, and duplicate status.
4. Record provenance and rights classification.
5. Copy or download the source into its skill directory.
6. Extract text locally without modifying the original.
7. Chunk extracted text with source and page or section metadata.
8. Run a corpus report showing accepted, rejected, duplicate, and incomplete
   records.

Rejected candidates retain only a safe path or URL, checksum when available,
and rejection reason. Sensitive extracted content is not retained.

## Git And Storage

The repository uses Git LFS from its first commit for binary source formats,
including PDF, DOC, DOCX, PPT, PPTX, XLS, XLSX, images, archives, audio, and
video.

Plain-text manifests, scripts, extracted text, and approved Markdown remain in
ordinary Git. Generated vector indexes and model caches are ignored because
they are reproducible and unsuitable for source control.

The parent Firecrawl repository will reference the private repository as a Git
submodule at `Interview Prep/RAG Sources`. No other part of the existing
`Interview Prep/` archive will be added to the parent repository.

## RAG Products

The private corpus supports two distinct outputs:

### V1 Agent Workflow

- Codex inventories and structures approved sources, prepares provenance
  records, drafts content, and runs deterministic repository checks.
- Claude may independently draft or review questions, pages, and case studies
  from the same approved source set.
- Each task receives only the minimum relevant source files rather than the
  entire archive.
- Outputs are saved as reviewable Markdown or JSONL artifacts with source IDs.
- One agent's generation should be reviewed by the other agent, or by the user,
  before it moves into an approved or publishable state.
- No unattended model API pipeline is part of V1. LM Studio or a programmatic
  model provider may be evaluated later as a separate design.

### Question Bank

- Retrieve passages by canonical skill and target difficulty.
- Use Claude or Codex to generate original MCQs into the existing structured
  question format.
- Verify answer keys independently with the other agent or explicit human
  review before publication.
- Store source IDs and URLs as provenance.
- Never persist copied source questions or long source passages in Supabase.

### Public Learning Pages And Case Studies

- Produce original explanations, examples, exercises, and case studies.
- Cite authoritative sources where factual support is required.
- Run similarity checks against source text before publication.
- Publish only files in `case-studies/approved/` or an equivalent reviewed
  export.
- Keep proprietary company data, copyrighted exhibits, and answer keys private.

## Initial Skill Coverage

The first corpus release covers the existing pilot skills:

- Machine Learning
- Product Strategy
- Management Consulting
- Financial Accounting

Initial local material will be reviewed in this order:

1. Management Consulting casebooks and interview frameworks
2. Product Management guides and case submissions
3. Accounting and finance course material
4. Machine Learning and analytics material

Firecrawl harvesting will prioritize gaps in authoritative coverage rather than
duplicate documents already present locally.

## Firecrawl Use

Firecrawl Cloud is used selectively for:

- Mapping official documentation and institutional resource hubs
- Rendering useful pages that direct HTTP cannot extract
- Capturing page content with canonical URL and retrieval metadata
- Discovering downloadable PDF or document links

Direct document downloads are preferred when available. Broad indiscriminate
crawls, copied interview-question sites, and low-authority SEO pages are
excluded.

## Security And Publication Gates

Before the first push:

- Confirm the GitHub repository is private.
- Confirm Git LFS patterns are active.
- Run secret and personal-data scans.
- Review every allowlisted source.
- Confirm no rejected or non-allowlisted archive files are staged.

Before public publication:

- Confirm the output is original and source-grounded.
- Confirm source redistribution restrictions are respected.
- Confirm no personal or confidential data appears.
- Confirm citations resolve to manifest records.
- Confirm the generation and independent-review agents are recorded.
- Require explicit approval before moving a draft into the approved set.

## Verification

Automated checks will cover:

- Manifest schema and unique source IDs
- File existence and checksums
- Allowlist-only imports
- Sensitive-path rejection
- Git LFS coverage for binary formats
- Duplicate detection
- Derived chunk provenance
- Public-output similarity and citation requirements
- Generation and review attribution for V1 artifacts

The initial repository is accepted when it is private, cloned locally at the
agreed path, has the documented structure and safeguards, passes its validation
checks, and contains a small reviewed source sample for each pilot skill.
