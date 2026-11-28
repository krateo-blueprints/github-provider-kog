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

`release-oci.yaml` has three jobs. The middle one is the organisation's release workflow,
`krateo-platformops/.github` `release-oci` 2.2.0, pinned by full commit SHA with its release in a
comment and moved by Dependabot.

1. **`preflight`** resolves the version (the tag, or `chart_version` on a manual run) and
   refuses the release before anything is published if the commit being released has no
   successful `lint.yaml` run (PUBLISHING.md rule 10).
2. **`release-oci`** does the rest in one call, in this order:
   - before anything is pushed: the image gate (no chart here references an image), the
     organisation's `release-preflight` (rules 12 and 13: a plain `X.Y.Z` with no `v`, no
     leading zeros, no pre-release and no build suffix, the same definition the publisher
     applies at index time), a check that `CHARTS_PUBLISH_TOKEN` is present and has no
     whitespace (it never prints or uses the value), and the index's own content gate on every
     package;
   - it stamps the `CHART_VERSION` placeholders in each `Chart.yaml`, discovers `chart/` and
     `config-chart/` as first-class charts, packages both and pushes them to
     `oci://ghcr.io/krateo-blueprints/charts`. A version already published with identical
     contents is skipped, and one published with different contents is refused;
   - it pulls both charts back from GHCR, so the index gets exactly the bytes GHCR holds
     (rule 1), and calls the organisation's publisher with `index_channel: operators`. Neither
     chart ships a CompositionDefinition, so neither is a blueprint. The publisher succeeds only
     once `https://krateo-blueprints.github.io/charts/operators/index.yaml` lists both and
     `helm pull --repo` installs each anonymously.
3. **`packages-are-our-two-charts`** reads the packages `release-oci` built and requires exactly
   `github-provider-kog` and `github-provider-kog-config` at the release version, as both
   `version` and `appVersion`. `release-oci` checks the index against the set it discovered, so
   a chart that discovery missed would fail nothing there. On a tag this runs after the push, so
   it reports a wrong set; on a rehearsal it stops one.

## Rehearsing a change to the release

A manual run is a dry run unless `dry_run` is set to `false`: it runs every check and builds
every package, pushes nothing, and uploads the packages as the `release-oci-charts` artifact.
A manual run's ref is a branch, so it needs `chart_version`:

```console
$ gh workflow run release-oci.yaml --ref <branch> -f chart_version=X.Y.Z
```

Use a version that is not yet published, or the version guard reports it as already published.
Rehearse every change to `release-oci.yaml` this way before merging it.

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
