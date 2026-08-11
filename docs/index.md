---
type: Component
title: krateo-github-provider-kog — index
description: The map of the krateo-github-provider-kog doc bundle — a Krateo KOG provider that exposes GitHub's git-write API (RepoContent, GitRef, PullRequest) as github.krateo.io Kubernetes kinds via oasgen-provider.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [krateo, kog, oasgen-provider, github, blueprint-authoring]
timestamp: 2026-08-11T00:00:00Z
---

# krateo-github-provider-kog

krateo-github-provider-kog is a Krateo **KOG** (Krateo OpenAPI Generation) provider,
built on [`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider)
0.9.x, that exposes GitHub's **git-write** REST API as Kubernetes kinds under the
`github.krateo.io` group:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `RepoContent` | `PUT /repos/{owner}/{repo}/contents/{path}` | create or update a file in a repo |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | create a branch / ref |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | open a pull request |

It is the in-cluster git transport for **Krateo portal blueprint authoring**: the
Autopilot blueprint builder writes a chart tree to a repo (`GitRef` →
`RepoContent` per file → `PullRequest`) entirely as `github.krateo.io` apiserver
CRs, so external CI can package and push the OCI chart on merge.

## The bundle (start here)

- [overview](./overview.md) — what the chart ships, how oasgen-provider turns it into
  live CRDs and controllers, and why the git-write kinds need a companion plugin.
- [usage](./usage.md) — install as a Krateo component, provision the token and
  Configuration CRs, drive the three kinds, and verify.
- [configuration](./configuration.md) — the whole surface: the one chart value, the
  RestDefinition mappings, the plugin routes and env, and the invariants that must hold.
- [api](./api.md) — the generated CRDs (`RepoContent`/`GitRef`/`PullRequest` + their
  `<Kind>Configuration`) and the CompositionDefinition the CDC derives from
  `values.schema.json`.
- [examples](./examples.md) — the runnable examples under `examples/`.
- [release](./release.md) — how a release ships (one tag → the chart on GHCR and the
  plugin image).
- [log](./log.md) — curated history.
- [llms.txt](./llms.txt) — the file-by-file index of this bundle.

## Layout

- `chart/` — the only first-class chart. It ships three `RestDefinition`s
  (`ogen.krateo.io/v1alpha1`), the trimmed OpenAPI 3.0 spec each references (as a
  `ConfigMap`, `tpl`-rendered so per-operation `servers` overrides resolve to the
  plugin), the plugin `Deployment` + `Service`, and `values.schema.json`.
- `chart/assets/` — the three trimmed OpenAPI specs (`repocontent.yaml`,
  `gitref.yaml`, `pullrequest.yaml`).
- `chart/samples/` — a `<Kind>Configuration` set (`configurations.yaml`) and one test
  CR per kind.
- `plugin/` — the stdlib-only Go `rest-dynamic-controller` plugin (`main.go`,
  `Dockerfile`) that normalizes the GitHub REST inconsistencies the pure OpenAPI
  mapping cannot express, so the generated CRs settle to Ready instead of looping.

There is no `CompositionDefinition` file checked in: when the chart is installed as a
Krateo component, the core-provider CDC generates its CompositionDefinition CRD from
`values.schema.json` ([api](./api.md)).
