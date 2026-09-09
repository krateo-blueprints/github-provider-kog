---
type: Log
title: github-provider-kog — log
description: Curated chronological history of github-provider-kog — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [log, history]
timestamp: 2026-09-09T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.

## 2026-09-09 — renamed to `github-provider-kog`, chart included

The repository and the Helm chart are both now `github-provider-kog`; they were
`krateo-github-provider-kog`. The chart name is what consumers pin, so it was renamed while
**nothing pins it yet** — the installer's `component-pins.yaml` has no entry for it — rather than
after, when a rename would mean re-pinning and a stale package.

The name was not free until now: a forked alternative (`github-provider-kog-chart`, a copy of
`krateoplatformops/github-provider-kog-chart`) already published `charts/github-provider-kog`.
That fork has been deleted along with its package, and this — the from-scratch provider — takes
the name.

Consequences worth knowing:

- New releases publish to `oci://ghcr.io/krateo-blueprints/charts/github-provider-kog`. The old
  `charts/krateo-github-provider-kog` package (one version, `0.1.11`) is now stale. Nothing
  references it; it can be deleted whenever someone wants to.
- **The plugin image deliberately keeps its old name**, `krateo-github-provider-kog-plugin`. The
  plugin is on its way out — every kind it serves is being moved to native RestDefinition features
  — so renaming it would publish a second package only to delete it again, and orphan the versions
  already pushed. When the plugin goes, its Deployment, Service and image go together.
- Rendered values are unchanged except the `app.kubernetes.io/part-of` label. The `pluginName`
  helper builds its name from `.Release.Name`, not the chart name, so
  `spec.selector.matchLabels` — which Kubernetes treats as immutable on a Deployment — is
  byte-identical. The rename is safe to roll onto an existing install.
- The Go module path moved with the repo
  (`github.com/krateo-blueprints/github-provider-kog/plugin`). Nothing imports it; the plugin is a
  single `main` package.

## 2026-09-09 — `Repository`: create the destination repo, not just write into it

A fourth kind, `Repository`, maps GitHub's repository API onto `github.krateo.io`: create
on `POST /orgs/{org}/repos`, get/update/delete on `/repos/{org}/{name}`. All four verbs
are **native** — `Repository` never touches the companion plugin, so its ConfigMap is
copied verbatim rather than `tpl`-rendered (the other three are `tpl`-rendered only
because they carry per-operation `servers` overrides pointing at the plugin).

It is ordered first in the authoring chain — `Repository` → `GitRef` → `RepoContent` (per
file) → `PullRequest`. Until now a blueprint could only be published into a repository
someone had already created by hand. `auto_init` defaults to `true` in the OAS, and that
default is load-bearing: a repository created without it has no commit and therefore no
default branch, so a `GitRef` has no base sha to branch from and a `RepoContent` has
nothing to commit against.

**`compareScope: identifiersAndStatus`, and what it costs.** Three fields in the create
body — `auto_init`, `gitignore_template`, `license_template` — are create-only: GitHub
accepts them on `POST` and never echoes them back on `GET`. Under the default `fullSpec`,
Observe compares every spec field against the GET response, so those three would read as
permanent drift and the controller would `PATCH` the repository on every single reconcile,
forever, against an API with a 5000 req/hr budget. `identifiersAndStatus` compares only
`name` plus the `additionalStatusFields`, which ends the loop — and its cost is real and
accepted: editing `description` or `private` on an existing CR is **not** pushed to
GitHub. For a create-once destination repository that trade is right. The enum has only
these two values (`fullSpec` | `identifiersAndStatus`), so the alternative is not a
narrower compare but dropping the three create-only fields from the create body — which
means losing `auto_init`, the thing that guarantees a default branch.

Two smaller decisions. The path parameters are named `org` and `name`, not GitHub's
`owner`/`repo`: the same two CR fields then serve the create path (`/orgs/{org}/repos`),
the create body (`name`) and the get/update/delete path (`/repos/{org}/{name}`), so the
generated CRD carries one pair of fields instead of an `org`/`owner` duplicate the author
has to keep in sync. And `POST /user/repos` is deliberately not modelled: a
`RestDefinition` has one create verb and cannot choose between two paths, and Krateo
destinations are org-owned.

`Repository` also asks more of the PAT than the other three — repository creation in the
org (classic token `repo`; fine-grained token org **Administration: read & write**) on top
of the contents/refs/pulls scopes. Its own `RepositoryConfiguration` joins the set in
`chart/samples/configurations.yaml`; all four may share a name.

Verified so far: `helm lint` clean; `helm template` renders 4 ConfigMaps + 4
RestDefinitions; every RD path and method cross-checked against its own OAS document; the
identifiers and `additionalStatusFields` confirmed present in the `Repository` response
schema; and the rendered RestDefinition accepted by the deployed
`restdefinitions.ogen.krateo.io` CRD on krateo-057 via `kubectl apply --dry-run=server`
under a throwaway name (nothing created, absence verified afterwards). There is **no**
live end-to-end run of `Repository` against GitHub yet.

Unrelated to the kind, and recorded here because this is the change set it landed in: the
GitHub repo is now `krateo-blueprints/github-provider-kog`. The Helm chart is still named
`github-provider-kog` and still publishes to `charts/github-provider-kog`;
that rename is deferred because the shorter name is currently held by another published
package.

## 2026-08-11 — Documentation Standard adoption

The repo adopts the Krateo Documentation Standard (OKF): the invariant docs bundle
(`index`/`overview`/`usage`/`configuration`/`api`/`examples`/`release`/`log` +
`llms.txt`), a runnable `examples/blueprint-authoring`, a rewritten six-section
`README.md`, and the shared `lint-docs` check wired into a new `lint.yaml`. Part of
krateo-platformops/installer#52.

## Design decisions worth keeping

- **KOG, not a forked provider.** The three git-write kinds are pure OpenAPI mappings
  (`RestDefinition` + trimmed spec); oasgen-provider (≥ 0.9.x) generates the CRDs and
  auto-deploys a `rest-dynamic-controller` per kind. The chart ships no controller of
  its own for those kinds.
- **A companion plugin only for what OpenAPI cannot express.** The plugin
  (`plugin/main.go`) is reached solely via per-operation OpenAPI `servers` overrides,
  for exactly the verbs that need it — GitRef create (auto-resolve base sha) and observe
  (git/ref-vs-git/refs asymmetry), RepoContent idempotent write + branch-aware,
  base64-canonicalizing observe, and PullRequest observe (flatten head/base). Every
  other verb goes straight to GitHub.
- **The plugin carries no credential.** It forwards the caller's `Authorization`
  header; the token lives in an out-of-band Secret referenced by the oasgen-generated
  `<Kind>Configuration` CRs, which the portal write-path only references.
- **Chart and plugin image co-version on one tag.** The plugin Deployment pins
  `:{{ .Chart.Version }}`; `release-image.yaml` publishes the image on the same
  bare-semver tag `release-oci.yaml` uses for the chart.
