---
type: Usage
title: github-provider-kog — usage
description: How to run the provider — install it as a Krateo component, provision the GitHub token Secret and one Configuration CR per kind, create the destination repository with Repository, author a chart tree with GitRef then RepoContent then PullRequest, and verify the generated CRDs and controllers.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, install, oasgen-provider, github, blueprint-authoring]
timestamp: 2026-08-11T00:00:00Z
---

# Usage

## Prerequisite

A Krateo cluster with `oasgen-provider` **≥ 0.9.x** running (it provides
`restdefinitions.ogen.krateo.io` and generates the CRDs + a controller per kind).

## Install — as a Krateo component

Per the Krateo "everything is a Composition" rule, this chart is installed as a
**component** — a `component-pins` entry that becomes a `CompositionDefinition`
reconciled by the core-provider CDC — not via `helm install`. The core-provider
generates this chart's CompositionDefinition CRD from `values.schema.json`
([api](./api.md)); pin the chart in the Installer and the CDC does the rest:

```yaml
# Installer CR — component-pins entry (illustrative)
- chart: github-provider-kog
  version: <released version>
  repository: oci://ghcr.io/krateo-blueprints/charts
```

For local development against a kind cluster only:

```console
$ helm upgrade --install github-provider-kog ./chart --namespace krateo-system
```

## Provision the token and the Configuration CRs

Each RestDefinition's OpenAPI declares a bearer `securityScheme`, so oasgen-provider
generates a per-kind `<Kind>Configuration` CRD and adds `spec.configurationRef` to
every resource CR. Provision, **out-of-band**, a token Secret plus one Configuration
CR per kind pointing at it. First the Secret:

```console
$ kubectl create secret generic gh-token \
    --namespace krateo-system \
    --from-literal=token=<YOUR_GITHUB_PAT>   # PAT scopes: repo (contents/refs/pulls write)
                                             # + repo creation in the org (Repository)
```

`Repository` needs **more** than the other three kinds: creating a repository in an
organization is an admin operation, not a contents/refs/pulls write. A classic token
needs `repo`; a fine-grained token needs the organization permission **Administration:
read & write** on top of the repository permissions the other three kinds use. If the
token is scoped only for the git-write kinds, `GitRef`/`RepoContent`/`PullRequest` still
work and only `Repository` fails.

Then one Configuration per kind (all four may share a name — the kind is implied by
the resource that references it); see `chart/samples/configurations.yaml`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepoContentConfiguration   # + GitRefConfiguration + PullRequestConfiguration
                                 # + RepositoryConfiguration
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

The Krateo portal write-path **references** these Configuration CRs
(`spec.configurationRef.name`); it never creates them or the Secret. The PAT is
created and stored by an operator, never handled by the browser or snowplow.

## Create the destination repository

`Repository` creates the repo everything else is written into, so it comes **first** —
`Repository` → `GitRef` → `RepoContent` (per file) → `PullRequest`. It is the one kind
that never routes through the plugin: create (`POST /orgs/{org}/repos`) and
get/update/delete (`GET`/`PATCH`/`DELETE /repos/{org}/{name}`) all go straight to
`api.github.com`. See `chart/samples/test-repository.yaml`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: Repository
metadata:
  name: test-demo-destination
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  org: krateo-blueprints
  name: demo-destination
  description: "Destination repository created by Krateo"
  private: true
  auto_init: true
```

Four things to know before you apply it:

- **Leave `auto_init: true`** (it is the OAS default). A repository created with
  `auto_init: false` has no commit and therefore no default branch, so a `GitRef` aimed
  at it has no base sha to branch from and a `RepoContent` has nothing to commit
  against — the rest of the chain fails until someone pushes by hand.
- **The path params are `org` and `name`, not GitHub's `owner`/`repo`.** Deliberate:
  the same two CR fields serve the create path (`/orgs/{org}/repos`), the create body
  (`name`) and the get/update/delete path (`/repos/{org}/{name}`), so the CRD carries
  one pair of fields instead of an `org`/`owner` duplicate to keep in sync. The
  downstream `GitRef`/`RepoContent`/`PullRequest` CRs keep GitHub's own `owner`/`repo`
  spelling — that pair is this `org`/`name` pair, named the way GitHub names it.
- **Editing an applied `Repository` does not reach GitHub.** The RestDefinition sets
  `compareScope: identifiersAndStatus` rather than the default `fullSpec` (the enum is
  only those two), so Observe compares `name` plus the status fields and nothing else.
  Under `fullSpec` the three create-only body fields — `auto_init`,
  `gitignore_template`, `license_template`, which GitHub accepts on POST and never
  echoes on GET — would read as permanent drift, and the controller would PATCH the
  repository on every reconcile, forever, against an API with a 5000 req/hr budget. The
  cost of the narrower scope is real: change `description` or `private` on an existing
  CR and it stays local; change it in GitHub instead. For a create-once destination
  repository that trade is the right one ([configuration](./configuration.md)).
- **Only the org-scoped create is modelled.** GitHub's other create endpoint,
  `POST /user/repos` for user-owned repos, is deliberately absent: a RestDefinition has
  one create verb and cannot choose between two paths, and Krateo destinations are
  org-owned. Create the repo under an organization, or create it outside Krateo and
  point `GitRef`/`RepoContent` at it.

`delete` maps to `DELETE /repos/{org}/{name}`, so deleting the CR deletes the repository
on GitHub. The full spec/status field list is in [api](./api.md).

The status fields carry what the next step needs: `full_name`, `clone_url`, `ssh_url`,
`html_url` and the `default_branch` the `GitRef` will branch from.

```console
$ kubectl get repository test-demo-destination -n krateo-system \
    -o jsonpath='{.status.full_name} {.status.default_branch}{"\n"}'
```

## Author a chart tree — the blueprint write-path

The other three kinds compose the git flow the Autopilot blueprint builder uses:
create a branch, write each file, open a PR. Apply them in order
([examples](./examples.md), `chart/samples/`):

1. **`GitRef`** — create the builder branch. Leave `sha` out and the provider resolves
   the repo's default-branch HEAD sha automatically, so an author never needs a commit
   sha:

   ```yaml
   apiVersion: github.krateo.io/v1alpha1
   kind: GitRef
   metadata:
     name: test-builder-branch
     namespace: krateo-system
   spec:
     configurationRef:
       name: github-blueprints-config
     owner: krateo
     repo: krateo-blueprints
     ref: refs/heads/builder/demo-branch
   ```

2. **`RepoContent`** — write each file on that branch. `content` is base64-encoded file
   bytes; omit `sha` to create, or let the provider update in place if the file exists.

3. **`PullRequest`** — open the PR from the builder branch into `main`.

## Verify

```console
$ # oasgen should generate the CRDs + a controller per kind
$ kubectl get crd | grep github.krateo.io
$ kubectl get deploy -n krateo-system \
    | grep -E 'repository|repocontent|gitref|pullrequest|plugin'
```

Set `krateo.io/connector-verbose: "true"` on a resource CR (as the samples do) and
watch `kubectl logs deploy/<release>-plugin` to see the observe/create URLs the
controller drives through the plugin. `Repository` is the exception: all four of its
verbs are native, so nothing it does shows up in the plugin log — read its own
controller's logs instead.
