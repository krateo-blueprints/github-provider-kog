---
type: Runbook
title: github-provider-kog — release
description: How a release ships — one plain-semver tag pushes both charts to GHCR at the same version and then publishes the same bytes to the krateo-blueprints helm index (operators channel). There is no image.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [release, oci, ghcr, chart]
timestamp: 2026-09-09T00:00:00Z
---

# Release

One plain-semver tag (`X.Y.Z`, **no** `v` prefix) releases everything. The tag push
triggers one workflow, `release-oci.yaml`, which follows the organisation's publishing
standard ([krateo-blueprints/charts `PUBLISHING.md`](https://github.com/krateo-blueprints/charts/blob/main/PUBLISHING.md)):
every chart is published twice, with the same bytes.

## What a tag ships

1. **`preflight`** refuses the release before anything is published if the tag is not plain
   semver, if the tagged commit has no successful `lint.yaml` run, or if
   `CHARTS_PUBLISH_TOKEN` is not configured. A failure after the GHCR push would leave a
   version in GHCR and missing from the index.
2. **`release-oci`** (the canonical org workflow) stamps the `CHART_VERSION` (and
   `SOURCE_REF`) placeholders in each `Chart.yaml` with the tag, discovers `chart/` and
   `config-chart/` as first-class charts, packages both, and pushes them to
   `oci://ghcr.io/krateo-blueprints/charts`. A collision guard refuses to push to a bare
   registry root, and a version already published with identical contents is skipped rather
   than re-pushed.
3. **`collect`** pulls both charts back from GHCR and uploads them as the `charts-dist`
   artifact. Pulling is what guarantees the index gets the bytes GHCR holds: `helm package`
   writes fresh timestamps, and a skipped push means the local archive was never published.
   It asserts the artifact holds exactly the two charts at the tag version.
4. **`publish-index`** calls the organisation's publisher,
   `krateo-blueprints/charts/.github/workflows/publish-chart.yaml@1`, with
   `channel: operators`. Neither chart ships a CompositionDefinition, so neither is a
   blueprint. The publisher stores the archives, merges the index and succeeds only once
   `https://krateo-blueprints.github.io/charts/operators/index.yaml` lists both and
   `helm pull --repo` installs each anonymously.

That is the whole release. `github-provider-kog` renders 32 ConfigMaps + 32 RestDefinitions
and `github-provider-kog-config` renders two Configurations. Neither has a Deployment, a
Service or an image reference. A tag publishes both at the same version, even when only one
changed. The companion plugin, its image and
`release-image.yaml` were deleted with the three kinds that needed them — the reason and
the restoration path are in the [log](./log.md) and in
[design-gitref](./design-gitref.md) / [design-repocontent](./design-repocontent.md) /
[design-pullrequest](./design-pullrequest.md).

## Steps

```console
$ git tag -a X.Y.Z -m "X.Y.Z: <summary>" && git push origin X.Y.Z
```

Use an **annotated** tag. On 2026-11-05 a lightweight `0.7.3` tag started no workflow in 14 minutes, while
the same commit tagged with `-a` started `release-oci` within seconds. Every earlier release was annotated.

Then verify the workflow went green and the chart exists in both places:

```console
$ helm show chart oci://ghcr.io/krateo-blueprints/charts/github-provider-kog --version X.Y.Z | head -3
$ helm pull github-provider-kog --repo https://krateo-blueprints.github.io/charts/operators --version X.Y.Z
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
