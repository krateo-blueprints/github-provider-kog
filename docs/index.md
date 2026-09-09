---
type: Component
title: github-provider-kog — index
description: The map of the github-provider-kog doc bundle — a Krateo KOG provider that exposes 31 GitHub resources (repository and git write, access, repository configuration, CI/CD, work tracking, governance) as github.krateo.io Kubernetes kinds via oasgen-provider.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, kog, oasgen-provider, github, blueprint-authoring]
timestamp: 2026-09-09T00:00:00Z
---

# github-provider-kog

github-provider-kog is a Krateo **KOG** (Krateo OpenAPI Generation) provider,
built on [`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider),
that exposes **31 GitHub REST resources** as Kubernetes kinds under the
`github.krateo.io` group.

It started as the in-cluster git transport for **Krateo portal blueprint authoring**:
the Autopilot blueprint builder creates the destination repo and writes a chart tree
into it (`Repository` → `GitRef` → `RepoContent` per file → `PullRequest`) entirely as
`github.krateo.io` apiserver CRs, so external CI can package and push the OCI chart on
merge. That chain is unchanged. Around it, the chart now covers the GitHub surface a
platform team otherwise configures by hand — who has access, how a repository is set
up, what CI/CD may do, and the org-level policy over both — as CRs a composition can
declare.

## The kinds

| Group | Kinds |
|-------|-------|
| **Repository and git write** | `Repository`, `RepoContent`, `GitRef`, `PullRequest` |
| **Access** | `Team`, `TeamRepo`, `TeamMembership`, `Collaborator`, `OrgMembership` |
| **Repository configuration** | `RepoWebhook`, `OrgWebhook`, `DeployKey`, `Environment`, `RepoRuleset`, `OrgRuleset`, `Autolink`, `BranchProtection` |
| **CI/CD** | `ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`, `DeploymentBranchPolicy`, `Workflow` |
| **Work tracking** | `Label`, `Milestone`, `Issue`, `Release`, `Deployment` |
| **Governance** | `CustomProperty`, `CodeSecurityConfig`, `AutomatedSecurityFixes` |

Four facts hold across the whole set:

- **All 31 are always installed.** The chart has no per-kind toggle: a RestDefinition
  costs nothing until a CR of its kind exists.
- **27 of the 31 are new, and every one of them is native.** The companion plugin still
  serves only `RepoContent`, `GitRef` and `PullRequest`, so 28 kinds never touch it
  ([overview](./overview.md)).
- **One PAT can drive the whole chart.** Every kind gets its own `<Kind>Configuration`
  auth kind, but they may all share one name — `chart/samples/configurations.yaml` now
  ships all 31 under `github-blueprints-config`. The rights that token needs do differ
  by kind ([usage](./usage.md)).
- **oasgen-provider ≥ 0.23.0 is required.** 23 of the 31 declare
  `compareScope: updatable`, which earlier versions do not accept.

Two GitHub surfaces are deliberately absent: Actions/Dependabot/Codespaces **secrets**,
which need a client-side LibSodium sealed box no RestDefinition can compute, and
`VulnerabilityAlerts`, whose GET never returns a body to derive a status from. Both are
explained in [overview](./overview.md) — note that **variables are not secrets** and are
covered.

## The bundle (start here)

- [overview](./overview.md) — what the 31 kinds cover, how oasgen-provider turns the
  chart into live CRDs and controllers, how each kind decides drift (`compareScope`),
  what keeps 28 kinds native, why the three git-write kinds still need a companion
  plugin, and where the coverage stops.
- [usage](./usage.md) — install as a Krateo component, provision the token and
  Configuration CRs, drive the kinds, and verify.
- [configuration](./configuration.md) — the whole surface: the one chart value, the
  RestDefinition mappings, the plugin routes and env, and the invariants that must hold.
- [api](./api.md) — the generated CRDs (the 31 resource kinds + their
  `<Kind>Configuration`) and the CompositionDefinition the CDC derives from
  `values.schema.json`.
- [examples](./examples.md) — the runnable examples under `examples/`.
- [release](./release.md) — how a release ships (one tag → the chart on GHCR and the
  plugin image).
- [log](./log.md) — curated history.
- [llms.txt](./llms.txt) — the file-by-file index of this bundle.

## Layout

- `chart/` — the only first-class chart. It ships 31 `RestDefinition`s
  (`ogen.krateo.io/v1alpha1`), the trimmed OpenAPI 3.0 spec each references (as a
  `ConfigMap`; the three git-write ones are `tpl`-rendered so per-operation `servers`
  overrides resolve to the plugin, the other 28 assets are copied verbatim), the plugin
  `Deployment` + `Service`, and `values.schema.json`.
- `chart/assets/` — the 31 trimmed OpenAPI specs, one per kind
  (`repository.yaml`, `repocontent.yaml`, `gitref.yaml`, `pullrequest.yaml`, and 27
  more).
- `chart/samples/` — the full `<Kind>Configuration` set (`configurations.yaml`, all 31)
  and one test CR per kind.
- `plugin/` — the stdlib-only Go `rest-dynamic-controller` plugin (`main.go`,
  `Dockerfile`) that normalizes, for the three git-write kinds, the GitHub REST
  inconsistencies the pure OpenAPI mapping cannot express, so the generated CRs settle
  to Ready instead of looping. The other 28 kinds are fully native and do not use it.

There is no `CompositionDefinition` file checked in: when the chart is installed as a
Krateo component, the core-provider CDC generates its CompositionDefinition CRD from
`values.schema.json` ([api](./api.md)).
