---
type: Component
title: github-provider-kog — index
description: The map of the github-provider-kog doc bundle — a Krateo KOG provider that exposes 29 GitHub resources (repository, access, repository configuration, CI/CD, work tracking, governance) as github.krateo.io Kubernetes kinds via oasgen-provider.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, kog, oasgen-provider, github, blueprint-authoring]
timestamp: 2026-09-09T00:00:00Z
---

# github-provider-kog

github-provider-kog is a Krateo **KOG** (Krateo OpenAPI Generation) provider,
built on [`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider),
that exposes **29 GitHub REST resources** as Kubernetes kinds under the
`github.krateo.io` group.

It started as the in-cluster git transport for **Krateo portal blueprint authoring** —
`Repository` → `GitRef` → `RepoContent` per file → `PullRequest`, entirely as
`github.krateo.io` apiserver CRs. That route has been superseded: the frontend now
publishes through a `BuilderPublish` claim over `git-provider`
(`AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"`), so the three git-write kinds
— and the companion proxy plugin only they needed — have been removed. What each did and
what a native restoration would take is recorded in
[design-repocontent](./design-repocontent.md),
[design-pullrequest](./design-pullrequest.md) and [design-gitref](./design-gitref.md).

What the chart covers is the GitHub surface a platform team otherwise configures by hand
— who has access, how a repository is set up, what CI/CD may do, and the org-level policy
over both — as CRs a composition can declare, with `Repository` creating the destination
itself.

## The kinds

| Group | Kinds |
|-------|-------|
| **Repository** | `Repository` |
| **Access** | `Team`, `TeamRepo`, `TeamMembership`, `Collaborator`, `OrgMembership` |
| **Repository configuration** | `RepoWebhook`, `OrgWebhook`, `DeployKey`, `Environment`, `RepoRuleset`, `OrgRuleset`, `Autolink`, `BranchProtection` |
| **CI/CD** | `ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`, `RunnerGroup`, `DeploymentBranchPolicy`, `Workflow` |
| **Work tracking** | `Label`, `Milestone`, `Issue`, `PullRequest`, `Release`, `Deployment` |
| **Governance** | `CustomProperty`, `CodeSecurityConfig`, `AutomatedSecurityFixes` |

Four facts hold across the whole set:

- **All 29 are always installed.** The chart has no per-kind toggle: a RestDefinition
  costs nothing until a CR of its kind exists.
- **Every one of the 29 is native**, calling `api.github.com` directly. The chart renders
  29 ConfigMaps + 29 RestDefinitions and ships **no runtime component** — no Deployment,
  no Service, no image, no proxy ([overview](./overview.md)).
- **One PAT can drive the whole chart.** Every kind gets its own `<Kind>Configuration`
  auth kind, but they may all share one name — `chart/samples/configurations.yaml`
  ships all 29 under `github-blueprints-config`. The rights that token needs do differ
  by kind ([usage](./usage.md)).
- **oasgen-provider ≥ 0.23.0 is required.** 24 of the 29 declare
  `compareScope: updatable`, which earlier versions do not accept.

Two GitHub surfaces are deliberately absent: Actions/Dependabot/Codespaces **secrets**,
which need a client-side LibSodium sealed box no RestDefinition can compute, and
`VulnerabilityAlerts`, whose GET never returns a body to derive a status from. Both are
explained in [overview](./overview.md) — note that **variables are not secrets** and are
covered.

## The bundle (start here)

- [overview](./overview.md) — what the 29 kinds cover, how oasgen-provider turns the
  chart into live CRDs and controllers, how each kind decides drift (`compareScope`),
  what keeps all 29 native, what the removed git-write kinds were, and where the coverage
  stops.
- [usage](./usage.md) — install as a Krateo component, provision the token and
  Configuration CRs, drive the kinds, and verify.
- [configuration](./configuration.md) — the whole surface: the one chart value, the
  RestDefinition mappings, and the invariants that must hold.
- [api](./api.md) — the generated CRDs (the 29 resource kinds + their
  `<Kind>Configuration`) and the CompositionDefinition the CDC derives from
  `values.schema.json`.
- [design-repocontent](./design-repocontent.md),
  [design-pullrequest](./design-pullrequest.md), [design-gitref](./design-gitref.md) —
  one per removed git-write kind: what the proxy plugin did for it, and the exact
  RestDefinition that would bring it back natively at oasgen-provider 0.23.0.
- [examples](./examples.md) — the runnable examples under `examples/`.
- [release](./release.md) — how a release ships (one tag → the chart on GHCR).
- [log](./log.md) — curated history.
- [llms.txt](./llms.txt) — the file-by-file index of this bundle.

## Layout

- `chart/` — the only first-class chart, and now the whole of what is shipped. It ships 29
  `RestDefinition`s (`ogen.krateo.io/v1alpha1`), the trimmed OpenAPI 3.0 spec each
  references (as a `ConfigMap`, copied in verbatim by `.Files.Get` — no kind needs a
  `tpl` pass), and `values.schema.json`. No `Deployment`, no `Service`, no image.
- `chart/assets/` — the 29 trimmed OpenAPI specs, one per kind
  (`repository.yaml`, `team.yaml`, `branchprotection.yaml`, and 25 more).
- `chart/samples/` — the full `<Kind>Configuration` set (`configurations.yaml`, all 29)
  and one test CR per kind.
- `docs/design-*.md` — one restoration design per removed git-write kind, so what the
  deleted plugin did survives the deletion.

There is no `CompositionDefinition` file checked in: when the chart is installed as a
Krateo component, the core-provider CDC generates its CompositionDefinition CRD from
`values.schema.json` ([api](./api.md)).
