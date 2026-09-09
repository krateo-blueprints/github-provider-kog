---
type: API
title: krateo-github-provider-kog — API
description: The CRDs this component brings into the cluster — the four resource kinds Repository/RepoContent/GitRef/PullRequest and their oasgen-generated <Kind>Configuration kinds under github.krateo.io, plus the CompositionDefinition the core-provider CDC derives from values.schema.json.
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

oasgen-provider (≥ 0.9.x) watches the four `RestDefinition`s and generates the CRDs
below under `resourceGroup` (default `github.krateo.io`, group version `v1alpha1`),
auto-deploying a `rest-dynamic-controller` per kind. Every resource CR carries a
`spec.configurationRef` (added by oasgen from the OpenAPI `securityScheme`) naming the
`<Kind>Configuration` that holds its token wiring.

### `Repository` — create the destination repository

| field | type | notes |
|---|---|---|
| `spec.configurationRef.name` | string | the `RepositoryConfiguration` to authenticate with |
| `spec.org` | string | the organization — a path param on every verb |
| `spec.name` | string | the repository name — the identifier, and the only required create-body field |
| `spec.description` / `spec.homepage` | string | repository metadata |
| `spec.private` | boolean | private repository |
| `spec.visibility` | string | repository visibility; the asset declares no enum, so GitHub validates it |
| `spec.has_issues` / `spec.has_wiki` / `spec.has_projects` | boolean | feature toggles |
| `spec.auto_init` | boolean | **default `true`** — create-only; see below |
| `spec.gitignore_template` / `spec.license_template` | string | create-only |
| `spec.default_branch` / `spec.archived` | string / boolean | update-only (they exist in the PATCH body, not the POST body) |
| `status.id` / `status.node_id` / `status.full_name` / `status.html_url` | | observed after create |
| `status.clone_url` / `status.ssh_url` / `status.default_branch` | string | what a downstream `GitRef`, `RepoContent` or CI job needs to reach the repo |

Verbs: create on `/orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}`.
Every verb is **native** — Repository never routes through the plugin. `spec` is the
union of both request bodies plus the path params, because oasgen unions the verbs
into one CRD.

The path parameters are named `org` and `name`, not GitHub's `owner`/`repo`, on
purpose: the same two CR fields then serve the create path (`/orgs/{org}/repos`), the
create body (`name`) and the get/update/delete path (`/repos/{org}/{name}`), so the
generated CRD carries **one** pair of fields instead of an `org`/`owner` duplicate the
author has to keep in sync ([configuration](./configuration.md)).

`auto_init` defaults to `true` and is load-bearing. A repository created with
`auto_init: false` has no commit and therefore no default branch, so a `GitRef` aimed
at it has no base sha to branch from and a `RepoContent` has nothing to commit
against. Repository is therefore first in the authoring chain: **Repository → GitRef →
RepoContent (per file) → PullRequest**.

Drift is compared with `compareScope: identifiersAndStatus`, not the default
`fullSpec`, so **editing `description` or `private` on an existing CR is not pushed to
GitHub** — only `name` and the status fields above are compared. The rationale and the
cost are in [configuration](./configuration.md).

GitHub's second create endpoint, `POST /user/repos` (user-owned repositories), is
deliberately not modelled: a `RestDefinition` has one create verb and cannot choose
between two paths, and Krateo destinations are org-owned.

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
bearer `securityScheme`: `RepositoryConfiguration`, `RepoContentConfiguration`,
`GitRefConfiguration`, `PullRequestConfiguration`. Each carries the token wiring a
resource CR references via `spec.configurationRef.name`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepositoryConfiguration   # + RepoContentConfiguration + GitRefConfiguration + PullRequestConfiguration
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

All four may share a name — the kind is implied by the resource that references it.
The referenced `Secret` is provisioned out-of-band ([usage](./usage.md)); the chart
ships none of this — see `chart/samples/configurations.yaml` for the full set.

`Repository` needs more from the token than the other three do: creating a repository
in an organization, not just writing contents/refs/pulls in one. A classic PAT needs
the `repo` scope; a fine-grained token needs the organization permission
**Administration: read & write**.
