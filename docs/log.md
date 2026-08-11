---
type: Log
title: krateo-github-provider-kog — log
description: Curated chronological history of krateo-github-provider-kog — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [log, history]
timestamp: 2026-08-11T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.

## 2026-08-11 — Documentation Standard adoption

The repo adopts the Krateo Documentation Standard (OKF): the invariant docs bundle
(`index`/`overview`/`usage`/`configuration`/`api`/`examples`/`release`/`log` +
`llms.txt`), a runnable `examples/blueprint-authoring`, a rewritten six-section
`README.md`, and the shared `lint-docs` check wired into a new `lint.yaml`. Part of
krateo-platformops/installer#52.

## Design decisions worth keeping

- **KOG, not a forked provider.** The three git-write kinds are pure OpenAPI mappings
  (`RestDefinition` + trimmed spec); oasgen-provider (≥ 0.9.x) generates the CRDs and
  auto-deploys a `rest-dynamic-controller` per kind. The chart ships no controller of
  its own for those kinds.
- **A companion plugin only for what OpenAPI cannot express.** The plugin
  (`plugin/main.go`) is reached solely via per-operation OpenAPI `servers` overrides,
  for exactly the verbs that need it — GitRef create (auto-resolve base sha) and observe
  (git/ref-vs-git/refs asymmetry), RepoContent idempotent write + branch-aware,
  base64-canonicalizing observe, and PullRequest observe (flatten head/base). Every
  other verb goes straight to GitHub.
- **The plugin carries no credential.** It forwards the caller's `Authorization`
  header; the token lives in an out-of-band Secret referenced by the oasgen-generated
  `<Kind>Configuration` CRs, which the portal write-path only references.
- **Chart and plugin image co-version on one tag.** The plugin Deployment pins
  `:{{ .Chart.Version }}`; `release-image.yaml` publishes the image on the same
  bare-semver tag `release-oci.yaml` uses for the chart.
