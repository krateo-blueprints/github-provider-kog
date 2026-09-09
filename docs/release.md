---
type: Runbook
title: github-provider-kog — release
description: How a release ships — one plain-semver tag drives both the canonical release-oci workflow (the chart to GHCR) and release-image (the plugin image on the same tag), so the chart's plugin Deployment always lines up with a published image.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [release, oci, ghcr, plugin-image]
timestamp: 2026-08-11T00:00:00Z
---

# Release

One plain-semver tag (`X.Y.Z`, **no** `v` prefix) releases everything. The tag push
triggers two workflows in parallel.

## What a tag ships

1. **`release-oci.yaml`** (the canonical, byte-identical org workflow) — stamps
   `chart/Chart.yaml`'s `CHART_VERSION` (and `SOURCE_REF`) placeholders with the tag,
   discovers `chart/` as the single first-class chart, packages it, and pushes to
   `oci://ghcr.io/krateo-blueprints/charts`. A collision guard refuses to push to a
   bare registry root, so the chart cannot collide with a same-named image.
2. **`release-image.yaml`** — builds and pushes the plugin image
   `ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:X.Y.Z` (linux/amd64,
   from `plugin/`) on the **same** bare-semver tag. The chart's plugin Deployment pins
   `:{{ .Chart.Version }}`, so every tag must publish the image or the chart would ask
   for one that was never built.

That co-versioning is the release invariant: chart X.Y.Z and plugin image X.Y.Z from
one ref ([configuration](./configuration.md)).

## Steps

```console
$ git tag X.Y.Z && git push origin X.Y.Z
```

Then verify both workflows went green and the artifacts exist:

```console
$ helm show chart oci://ghcr.io/krateo-blueprints/charts/github-provider-kog --version X.Y.Z | head -3
$ docker manifest inspect ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:X.Y.Z >/dev/null && echo image ok
```

## PR-time checks

- **`security.yml`** runs the shared org security workflow on every push and PR to
  `main`.
- **`lint.yaml`** runs the shared docs-standard linter (`lint-docs`) on every PR, which
  enforces this bundle: the core files, per-file frontmatter, resolvable links, and the
  README's six sections.

`release-oci.yaml` and `release-image.yaml` only fire on a bare-semver tag, never on a
PR, so `Chart.yaml`'s `CHART_VERSION` placeholder stays intact until a real release.

## Version pinning downstream

Consumers pin the chart by explicit `version` in the Installer component-pins
([usage](./usage.md)); nothing tracks `latest`. Both the chart version and the plugin
image tag are immutable per release.
