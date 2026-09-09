---
type: Architecture
title: github-provider-kog — overview
description: What the chart ships and how it works — RestDefinitions plus trimmed OpenAPI specs that oasgen-provider turns into github.krateo.io CRDs and a controller per kind (Repository, RepoContent, GitRef, PullRequest), and the companion plugin that normalizes GitHub's REST inconsistencies on the three git-write kinds so the CRs settle to Ready.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, kog, oasgen-provider, rest-dynamic-controller, github]
timestamp: 2026-08-11T00:00:00Z
---

# Overview

github-provider-kog exposes GitHub's repository and git-write API as
`github.krateo.io` Kubernetes kinds. It ships **no controller of its own** for any of
its four kinds — it declares the API mapping and lets `oasgen-provider` generate the
CRDs and spawn a `rest-dynamic-controller` per kind. One companion plugin fills the
gaps the OpenAPI mapping cannot express, for the three git-write kinds that need it.

## What the chart ships

The chart (`chart/`) renders, per kind (Repository / RepoContent / GitRef /
PullRequest):

| manifest | kind | role |
|---|---|---|
| `rd-<kind>.yaml` | `RestDefinition` (ogen.krateo.io/v1alpha1) | the API mapping: `resource.kind`, identifiers, the per-verb method/path table, request-field mappings |
| `configmap-<kind>.yaml` | `ConfigMap` | the trimmed OpenAPI 3.0 spec the RestDefinition references via `oasPath: configmap://...` |

Three of those ConfigMaps are `tpl`-rendered, because their spec carries a
per-operation `servers` override that has to resolve to the plugin's in-cluster URL.
`configmap-repository.yaml` is a plain `.Files.Get`: Repository has no such override,
so its asset is copied verbatim and contains no template action.

Plus one shared plugin workload:

| manifest | kind | role |
|---|---|---|
| `deployment-plugin.yaml` | `Deployment` | the `rest-dynamic-controller` plugin (`ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:<chart version>`) |
| `service-plugin.yaml` | `Service` (ClusterIP) | fronts the plugin at `http://<release>-plugin.<namespace>.svc:8080` |

Every generated CRD lands under `resourceGroup` (default `github.krateo.io`), the
chart's single value ([configuration](./configuration.md)).

## How oasgen-provider turns this into live kinds

`oasgen-provider` (installed cluster-wide, ≥ 0.9.x) watches the four
`RestDefinition`s. For each it:

1. reads the referenced OpenAPI ConfigMap (`configmap://<ns>/<name>/<file>`),
2. generates the CRD under `github.krateo.io` (`Repository`, `RepoContent`, `GitRef`,
   `PullRequest`), unioning the request fields across the mapped verbs into the CRD's
   `spec`, and
3. **auto-deploys a `rest-dynamic-controller` Deployment per kind**, which reconciles
   each CR by calling the mapped HTTP verbs (create/get/update/delete).

Because every RestDefinition's OpenAPI declares a bearer `securityScheme`,
oasgen-provider (0.9.x) also generates a per-kind **`<Kind>Configuration`** CRD
(`RepositoryConfiguration` / `RepoContentConfiguration` / `GitRefConfiguration` /
`PullRequestConfiguration`) and adds a `spec.configurationRef` field to every resource
CR — that is where the GitHub token wiring lives ([usage](./usage.md),
[api](./api.md)).

## Where Repository sits

`Repository` creates the destination itself, so the authoring chain now starts one
step earlier:

`Repository` → `GitRef` → `RepoContent` (per file) → `PullRequest`.

Before it, the three git-write kinds could only write into a repository someone had
already created by hand — a brand-new blueprint had a manual step in front of it that
no CR expressed. With `Repository` the whole chain is `github.krateo.io` CRs, and
order matters: the repo must exist and be initialised before a `GitRef` or
`RepoContent` aimed at it can succeed.

Four things about the mapping are worth stating plainly:

- **Every verb is native.** create `POST /orgs/{org}/repos`; get, update and delete
  `GET` / `PATCH` / `DELETE /repos/{org}/{name}`. All four go straight to
  `api.github.com` — `Repository` never touches the plugin.
- **`compareScope: updatable`, not the default `fullSpec`.** Under `fullSpec`, Observe
  compares every spec field against the GET response, and three create-body fields —
  `auto_init`, `gitignore_template`, `license_template` — are create-only: GitHub
  accepts them on POST and never echoes them on GET. They would read as permanent
  drift, and the controller would PATCH the repository on every reconcile, forever,
  against an API with a 5000 req/hr budget. `updatable` compares exactly the fields the
  PATCH body can express, so those three drop out while every mutable field stays
  compared and fixable. It requires an update verb, which this resource has, and needs
  oasgen-provider **0.23.0** or newer.
- **`auto_init` defaults to true, and it is load-bearing.** A repository created with
  `auto_init=false` has no commit and therefore no default branch, so a `GitRef` aimed
  at it has no base sha to branch from and a `RepoContent` has nothing to commit
  against.
- **The path parameters are `org` and `name`, not GitHub's `owner`/`repo`.**
  Deliberate: the same two CR fields then serve the create path
  (`/orgs/{org}/repos`), the create body (`name`) and the get/update/delete path
  (`/repos/{org}/{name}`), so the generated CRD carries one pair of fields instead of
  an `org`/`owner` duplicate the author has to keep in sync.

One endpoint is deliberately left out: **`POST /user/repos`**, GitHub's create for
user-owned repositories. A RestDefinition has a single create verb and cannot choose
between two paths, so only the org-scoped create is modelled; Krateo destinations are
org-owned.

## Why the git-write kinds need a plugin

GitHub's git-write endpoints have quirks a pure OpenAPI-to-HTTP mapping cannot express;
left alone, a `rest-dynamic-controller` observes the wrong thing, sees spurious drift,
and re-issues create/update forever — the CR never reaches Ready. The RestDefinitions
point the affected verbs at the plugin's in-cluster URL (a per-operation OpenAPI
`servers` override, resolved through `tpl` in the ConfigMaps — see
`chart/templates/_helpers.tpl`), so the controller calls the plugin for exactly those
verbs; **every other verb still goes straight to GitHub**. The plugin
(`plugin/main.go`) fixes:

- **GitRef create** — GitHub requires the base commit `sha`, which a portal/Autopilot
  author has no way to know. When the CR omits `sha`, the plugin resolves the repo's
  default-branch HEAD sha and injects it, so naming only the new `ref` just works.
- **GitRef observe** — GitHub's get uses `git/ref/{ref}` (no `refs/` prefix) while
  create/update use `git/refs`. The plugin exposes a `/gitref/...` route that maps
  onto the correct get path, so a just-created ref is FOUND instead of 404-looping into
  "422 Reference already exists".
- **RepoContent write** — makes the PUT idempotent create-or-update: on a 422 for an
  existing file with no `sha`, it fetches the file's current sha on the target branch
  and retries once, so `RepoContent` can update a file in place, not only create it.
  It also flattens GitHub's nested `content{}` response to the root so the controller's
  same-level field compare succeeds.
- **RepoContent observe** — reads from the CR's `branch` (forwarded to GitHub as
  `?ref`, with multi-level percent-decoding for `builder/x`-style refs so a file on a
  builder branch is found), and canonicalizes GitHub's newline-wrapped base64 `content`
  so real drift is detected without false-looping on encoding.
- **PullRequest observe** — flattens GitHub's `head`/`base` objects to their `ref`
  strings so the controller's string-vs-object compare stops looping "update" and
  422-ing on a closed PR.

The plugin is a tiny stdlib-only Go service on a distroless `nonroot` base
(`plugin/Dockerfile`); it forwards the caller's `Authorization` header verbatim and
holds no credentials of its own.

## Trust boundary

The chart holds no secret. The GitHub token lives in a `Secret` provisioned
out-of-band; each `<Kind>Configuration` points at it; each resource CR references a
Configuration via `spec.configurationRef.name`. The Krateo portal write-path only ever
**references** these Configuration CRs — it never creates them or the Secret, and the
token is never handled by the browser or snowplow ([usage](./usage.md)).

`Repository` raises the bar on the token itself: creating a repository needs repo
creation rights in the org, which is more than the contents/refs/pulls access the
other three kinds need — a classic token needs `repo`, a fine-grained token needs the
org permission **Administration: read & write** ([usage](./usage.md)).
