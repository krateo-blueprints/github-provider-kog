---
type: API
title: krateo-github-provider-kog — API
description: The CRDs this component brings into the cluster — the three git-write resource kinds RepoContent/GitRef/PullRequest and their oasgen-generated <Kind>Configuration kinds under github.krateo.io, plus the CompositionDefinition the core-provider CDC derives from values.schema.json.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [krateo, crd, compositiondefinition, github, oasgen-provider]
timestamp: 2026-08-11T00:00:00Z
---

# API

Two layers of API. The chart itself is registered through a **CompositionDefinition**;
once reconciled, oasgen-provider brings the **`github.krateo.io` resource kinds** into
the cluster.

## The CompositionDefinition (the chart's own registration)

There is no `CompositionDefinition` file checked into this repo. When the chart is
installed as a Krateo component, the core-provider CDC generates the CompositionDefinition
CRD from `chart/values.schema.json`. The registration points at the published chart:

```yaml
apiVersion: core.krateo.io/v1alpha1
kind: CompositionDefinition
metadata:
  name: krateo-github-provider-kog
  namespace: krateo-system
spec:
  chart:
    url: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
    version: <released version>
```

From `chart/Chart.yaml`, core-provider derives the generated composition API: **Kind**
from `name` (dashes dropped, CamelCased → `KrateoGithubProviderKog`) and **apiVersion**
from `version` (`X.Y.Z` → `composition.krateo.io/vX-Y-Z`). The composition's `spec` is
typed by `values.schema.json`, whose only knob is the scalar `resourceGroup`
([configuration](./configuration.md)).

## The generated `github.krateo.io` kinds

oasgen-provider (≥ 0.9.x) watches the three `RestDefinition`s and generates the CRDs
below under `resourceGroup` (default `github.krateo.io`, group version `v1alpha1`),
auto-deploying a `rest-dynamic-controller` per kind. Every resource CR carries a
`spec.configurationRef` (added by oasgen from the OpenAPI `securityScheme`) naming the
`<Kind>Configuration` that holds its token wiring.

### `RepoContent` — create/update a file

| field | type | notes |
|---|---|---|
| `spec.configurationRef.name` | string | the `RepoContentConfiguration` to authenticate with |
| `spec.owner` / `spec.repo` | string | the repository |
| `spec.path` | string | the file path — the identifier |
| `spec.branch` | string | the branch to read/write (observe forwards it as `?ref`) |
| `spec.message` | string | the commit message |
| `spec.content` | string | base64-encoded file bytes |
| `spec.sha` | string | omit to create; supply (or let the plugin auto-fetch) to update |
| `status.sha` / `status.html_url` | string | observed after create/update |

Verbs: create/update/get/delete all on `/repos/{owner}/{repo}/contents/{path}` (create,
update and get routed through the plugin).

### `GitRef` — create a branch/ref

| field | type | notes |
|---|---|---|
| `spec.configurationRef.name` | string | the `GitRefConfiguration` |
| `spec.owner` / `spec.repo` | string | the repository |
| `spec.ref` | string | full ref, e.g. `refs/heads/builder/x` — the identifier |
| `spec.sha` | string | optional; omit and the plugin resolves the default-branch HEAD sha |
| `status.node_id` / `status.url` | string | observed after create |

Verbs: create on `/repos/{owner}/{repo}/git/refs` (via the plugin), get on
`/gitref/{owner}/{repo}/{ref}` (via the plugin), update/delete on
`/repos/{owner}/{repo}/git/refs/{ref}`.

### `PullRequest` — open a PR

| field | type | notes |
|---|---|---|
| `spec.configurationRef.name` | string | the `PullRequestConfiguration` |
| `spec.owner` / `spec.repo` | string | the repository |
| `spec.head` / `spec.base` | string | source and target branches |
| `spec.title` / `spec.body` | string | PR title and body |
| `status.number` / `status.html_url` / `status.state` | | observed after create; `number` sources `pull_number` for get/update |

`pull_number` is **excluded** from spec (GitHub assigns it on create); get and update
source it from `status.number` via the RestDefinition's `requestFieldMapping`. Verbs:
create on `/repos/{owner}/{repo}/pulls`, get on `.../pulls/{pull_number}` (via the
plugin), update on `.../pulls/{pull_number}`.

## The `<Kind>Configuration` kinds

For each resource kind, oasgen generates a `<Kind>Configuration` CRD from the OpenAPI
bearer `securityScheme`: `RepoContentConfiguration`, `GitRefConfiguration`,
`PullRequestConfiguration`. Each carries the token wiring a resource CR references via
`spec.configurationRef.name`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepoContentConfiguration   # + GitRefConfiguration + PullRequestConfiguration
metadata:
  name: github-blueprints-config
  namespace: krateo-system
spec:
  authentication:
    bearer:
      tokenRef:
        name: gh-token
        namespace: krateo-system
        key: token
```

All three may share a name — the kind is implied by the resource that references it.
The referenced `Secret` is provisioned out-of-band ([usage](./usage.md)); the chart
ships none of this — see `chart/samples/configurations.yaml` for the full set.
