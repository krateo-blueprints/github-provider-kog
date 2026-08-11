---
type: ExampleIndex
title: krateo-github-provider-kog — examples
description: Index of the runnable examples under examples/ — the end-to-end blueprint-authoring flow (GitRef then RepoContent then PullRequest) against a scratch repo.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [examples, github, blueprint-authoring]
timestamp: 2026-08-11T00:00:00Z
---

# Examples

- [examples/blueprint-authoring](../examples/blueprint-authoring/README.md) — the
  end-to-end write-path the Autopilot blueprint builder drives, as three
  `github.krateo.io` CRs applied in order: a `GitRef` creates the builder branch, a
  `RepoContent` writes a file onto it, and a `PullRequest` opens the PR into `main`. It
  reuses the `chart/samples/` CRs and shows the one-time token + `<Kind>Configuration`
  wiring they reference.
