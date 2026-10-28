---
type: Runbook
title: github-provider-kog — release
description: How a release ships — one plain-semver tag drives the canonical release-oci workflow, which packages the chart to GHCR. The chart is the only artifact this repo publishes: there is no image and nothing to co-version with it.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [release, oci, ghcr, chart]
timestamp: 2026-09-09T00:00:00Z
---

# Release

One plain-semver tag (`X.Y.Z`, **no** `v` prefix) releases everything. The tag push
triggers one workflow.

## What a tag ships

1. **`release-oci.yaml`** (the canonical, byte-identical org workflow) — stamps
   `chart/Chart.yaml`'s `CHART_VERSION` (and `SOURCE_REF`) placeholders with the tag,
   discovers `chart/` as the single first-class chart, packages it, and pushes to
   `oci://ghcr.io/krateo-blueprints/charts`. A collision guard refuses to push to a
   bare registry root, so the chart cannot collide with a same-named image.

That is the whole release. The chart renders 30 ConfigMaps + 30 RestDefinitions and
nothing else — no Deployment, no Service, no image reference — so there is no second
artifact and no co-versioning invariant to keep. The companion plugin, its image and
`release-image.yaml` were deleted with the three kinds that needed them — the reason and
the restoration path are in the [log](./log.md) and in
[design-gitref](./design-gitref.md) / [design-repocontent](./design-repocontent.md) /
[design-pullrequest](./design-pullrequest.md).

## Steps

```console
$ git tag X.Y.Z && git push origin X.Y.Z
```

Then verify the workflow went green and the chart exists:

```console
$ helm show chart oci://ghcr.io/krateo-blueprints/charts/github-provider-kog --version X.Y.Z | head -3
```

## PR-time checks

- **`security.yml`** runs the shared org security workflow on every push and PR to
  `main`.
- **`lint.yaml`** runs the shared docs-standard linter (`lint-docs`) on every PR, which
  enforces this bundle: the core files, per-file frontmatter, resolvable links, and the
  README's six sections.

`release-oci.yaml` only fires on a bare-semver tag, never on a PR, so `Chart.yaml`'s
`CHART_VERSION` placeholder stays intact until a real release.

## Version pinning downstream

Consumers pin the chart by explicit `version` in the Installer component-pins
([usage](./usage.md)); nothing tracks `latest`. Each released chart version is immutable.
