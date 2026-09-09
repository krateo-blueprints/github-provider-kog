---
type: Architecture
title: github-provider-kog — overview
description: What the chart ships and how it works — 31 RestDefinitions plus trimmed OpenAPI specs that oasgen-provider turns into github.krateo.io CRDs and a controller per kind, how each kind decides drift via compareScope, what keeps 28 kinds native, and the companion plugin that normalizes GitHub's REST inconsistencies on the three git-write kinds so the CRs settle to Ready.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, kog, oasgen-provider, rest-dynamic-controller, github]
timestamp: 2026-09-09T00:00:00Z
---

# Overview

github-provider-kog exposes 31 GitHub REST resources as `github.krateo.io` Kubernetes
kinds. It ships **no controller of its own** for any of them — it declares the API
mapping and lets `oasgen-provider` generate the CRDs and spawn a
`rest-dynamic-controller` per kind. One companion plugin fills the gaps the OpenAPI
mapping cannot express, for the three git-write kinds that need it; the other 28 kinds
call `api.github.com` directly.

## What the chart covers

Six groups. Each row is one kind, its primary endpoint, and what a CR of it expresses;
the per-verb tables live in [configuration](./configuration.md) and the generated fields
in [api](./api.md).

### Repository and git write

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `Repository` | `POST /orgs/{org}/repos` | the destination repository (org-owned) |
| `RepoContent` | `PUT /repos/{owner}/{repo}/contents/{path}` | a file in a repo, created or updated in place |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | a branch / ref |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | an open pull request |

### Access

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `Team` | `POST /orgs/{org}/teams` | an org team; item verbs address it by the `team_slug` GitHub derives from the name, read back from `status.slug`, so a rename converges |
| `TeamRepo` | `PUT /orgs/{org}/teams/{team_slug}/repos/{owner}/{repo}` | one team's permission on one repository |
| `TeamMembership` | `PUT /orgs/{org}/teams/{team_slug}/memberships/{username}` | a user's role in a team; `status.state` separates an accepted membership from a pending invitation |
| `Collaborator` | `PUT /repos/{owner}/{repo}/collaborators/{login}` | a direct repository grant; observed by a `findby` over the collaborator list |
| `OrgMembership` | `PUT /orgs/{org}/memberships/{username}` | organization membership and role; `status.state` is `pending` until the invitation is accepted |

### Repository configuration

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `RepoWebhook` | `POST /repos/{owner}/{repo}/hooks` | a repository webhook — delivery URL, content type, events, active, secret |
| `OrgWebhook` | `POST /orgs/{org}/hooks` | the same at org scope (no `test_url`; org hooks have none) |
| `DeployKey` | `POST /repos/{owner}/{repo}/keys` | a deploy key — immutable upstream: changing one means delete and recreate |
| `Environment` | `PUT /repos/{owner}/{repo}/environments/{environment_name}` | a deployment environment and its branch policy |
| `RepoRuleset` | `POST /repos/{owner}/{repo}/rulesets` | a repository ruleset — rules, conditions, bypass actors |
| `OrgRuleset` | `POST /orgs/{org}/rulesets` | the same at org scope |
| `Autolink` | `POST /repos/{owner}/{repo}/autolinks` | an autolink reference — immutable, like `DeployKey` |
| `BranchProtection` | `PUT /repos/{owner}/{repo}/branches/{branch}/protection` | the classic branch-protection document of one branch |

### CI/CD

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `ActionsVariableRepo` | `POST /repos/{owner}/{repo}/actions/variables` | a repository Actions variable |
| `ActionsVariableOrg` | `POST /orgs/{org}/actions/variables` | an org Actions variable and its visibility |
| `EnvironmentVariable` | `POST /repos/{owner}/{repo}/environments/{environment_name}/variables` | the same resource one scope deeper |
| `RunnerGroup` | `POST /orgs/{org}/actions/runner-groups` | a self-hosted runner group |
| `DeploymentBranchPolicy` | `POST /repos/{owner}/{repo}/environments/{environment_name}/deployment-branch-policies` | one branch or tag pattern allowed to deploy to an environment |
| `Workflow` | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` | whether a workflow file is enabled — create enables, delete disables; it never creates the file |

### Work tracking

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `Label` | `POST /repos/{owner}/{repo}/labels` | a label; renaming is not expressible (below) |
| `Milestone` | `POST /repos/{owner}/{repo}/milestones` | a milestone; `due_on` is create-only (below) |
| `Issue` | `POST /repos/{owner}/{repo}/issues` | an issue — title, body, state, state reason |
| `Release` | `POST /repos/{owner}/{repo}/releases` | a release |
| `Deployment` | `POST /repos/{owner}/{repo}/deployments` | an immutable deployment record |

### Governance

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `CustomProperty` | `PUT /orgs/{org}/properties/schema/{property_name}` | an org custom-property definition |
| `CodeSecurityConfig` | `POST /orgs/{org}/code-security/configurations` | an org code-security configuration |
| `AutomatedSecurityFixes` | `PUT /repos/{owner}/{repo}/automated-security-fixes` | whether Dependabot security updates are on for a repository |

`CodeSecurityConfig` is named that, not `CodeSecurityConfiguration`, on purpose: oasgen
appends `Configuration` to every kind to build its auth kind, so the longer name would
have produced `CodeSecurityConfigurationConfiguration`. The generated auth kind is
`CodeSecurityConfigConfiguration`.

## What the chart ships

The chart (`chart/`) renders, per kind, two manifests:

| manifest | kind | role |
|---|---|---|
| `rd-<kind>.yaml` | `RestDefinition` (ogen.krateo.io/v1alpha1) | the API mapping: `resource.kind`, identifiers, additional status fields, `compareScope`, the per-verb method/path table, request-field mappings |
| `configmap-<kind>.yaml` | `ConfigMap` | the trimmed OpenAPI 3.0 spec the RestDefinition references via `oasPath: configmap://...` |

Three of those ConfigMaps — `repocontent`, `gitref`, `pullrequest` — are `tpl`-rendered,
because their spec carries a per-operation `servers` override that has to resolve to the
plugin's in-cluster URL. The other 28 are a plain `.Files.Get`: those kinds are fully
native, so their assets are copied verbatim and contain no template action.

Plus one shared plugin workload:

| manifest | kind | role |
|---|---|---|
| `deployment-plugin.yaml` | `Deployment` | the `rest-dynamic-controller` plugin (`ghcr.io/krateo-blueprints/krateo-github-provider-kog-plugin:<chart version>`) |
| `service-plugin.yaml` | `Service` (ClusterIP) | fronts the plugin at `http://<release>-plugin.<namespace>.svc:8080` |

Every generated CRD lands under `resourceGroup` (default `github.krateo.io`), the
chart's single value ([configuration](./configuration.md)). There is no per-kind toggle:
all 31 RestDefinitions are always installed, because a RestDefinition costs nothing
until a CR of its kind exists.

## How oasgen-provider turns this into live kinds

`oasgen-provider` (installed cluster-wide) watches the 31 `RestDefinition`s. For each it:

1. reads the referenced OpenAPI ConfigMap (`configmap://<ns>/<name>/<file>`),
2. generates the CRD under `github.krateo.io`, unioning the request fields across the
   mapped verbs into the CRD's `spec`, and
3. **auto-deploys a `rest-dynamic-controller` Deployment per kind**, which reconciles
   each CR by calling the mapped HTTP verbs (create/get/update/delete).

The required version is **≥ 0.23.0**: 23 of the 31 RestDefinitions declare
`compareScope: updatable`, which older oasgen-provider does not accept (that field is
what 0.23.0 added). 0.23.0 is also the version the whole set was validated against.

Because every RestDefinition's OpenAPI declares a bearer `securityScheme`,
oasgen-provider also generates a per-kind **`<Kind>Configuration`** CRD — 31 of them,
`RepositoryConfiguration` through `AutomatedSecurityFixesConfiguration` — and adds a
`spec.configurationRef` field to every resource CR. That is where the GitHub token
wiring lives ([usage](./usage.md), [api](./api.md)).

## How each kind decides drift

Every reconcile compares the CR's spec against what GitHub returns, and `compareScope`
says which fields take part. The failure it guards against is specific: a spec field the
response **does** carry, in a shape or a server-normalised value the update can never fix,
reads as permanent drift, so the controller re-issues an update on every reconcile,
forever, against an API with a 5000 req/hr budget. A spec key the response does *not*
carry — create-only fields, path parameters — is skipped by the comparison under every
scope and cannot drift at all. The rule, with the controller code that implements it, is
in [configuration](./configuration.md).

| scope | kinds | why |
|---|---|---|
| `updatable` | the other 23 | compares exactly what the update body can express, derived from the OAS. **Load-bearing** where the response carries a key the update cannot fix — `TeamRepo`'s `owner`, `Issue`'s `labels`, `Milestone`'s `due_on`, the webhooks' `config.secret`, `Collaborator`'s effective `role_name`. **Defensive** on the rest, whose only surplus `fullSpec` keys are create-only fields or path parameters: the response omits those, the comparison skips them, and the two scopes agree today. Requires an update verb, and oasgen-provider ≥ 0.23.0. |
| `fullSpec` (left unset, 5) | `RepoContent`, `GitRef`, `PullRequest`, `Workflow`, `AutomatedSecurityFixes` | the three git-write kinds have their response shapes normalized by the plugin instead. `Workflow` and `AutomatedSecurityFixes` have no update verb at all, so `updatable` is unavailable — but their specs hold nothing except path parameters, which the response does not carry, and the comparison skips a spec key absent from the response, so fullSpec compares nothing and cannot report false drift. |
| `fullSpec` (set explicitly, 1) | `Autolink` | also has no update verb, and here fullSpec is the point rather than a fallback: the GET returns the whole resource, so a synced autolink never drifts, and an edited CR *should* report drift — an autolink is immutable, and the operator has to delete and recreate it. `identifiersAndStatus` would report Ready while the spec and the repository disagreed. |
| `identifiersAndStatus` (2) | `DeployKey`, `Deployment` | no update verb either, so `updatable` is unavailable — but unlike `Autolink` these carry spec fields fullSpec would compare and nothing could fix: a multi-line SSH public key whose byte-identical echo cannot be verified read-only; a deployment's `environment`, which a CI job posting a deployment status can rewrite. (Their create-only fields — `auto_merge`, `required_contexts` — are absent from the response and skipped either way.) The status list is chosen so the compared set contains no spec field at all: the resource exists, therefore it is up to date — the honest model of an immutable record, and a deleted one is still detected, because the GET 404s and the controller recreates it. |

The reasoning for each setting is written in the RestDefinition that carries it
(`chart/templates/rd-<kind>.yaml`), next to the line it justifies.

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
- **`compareScope: updatable`, not the default `fullSpec` — defensively.** It compares
  exactly the fields the PATCH body can express. The three create-only fields
  (`auto_init`, `gitignore_template`, `license_template`) are never echoed on GET, so the
  comparison skips them under either scope and they cannot loop; every spec field the GET
  *does* echo is in the PATCH body, so the two scopes agree today. `updatable` is set
  because it states the intent explicitly and stays correct if a non-updatable field is
  added later. It requires an update verb, which this resource has, and needs
  oasgen-provider **0.23.0** or newer ([configuration](./configuration.md)).
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

## What keeps 28 kinds native

Every one of the 27 kinds added around the original four is native — no plugin hop, no
proxy. That is possible because a RestDefinition expresses more than a path table, and
the quirks that would otherwise need a proxy are handled at the mapping layer:

- **Server-assigned identifiers.** `excludedSpecFields` keeps an id the author cannot
  know out of the CR spec, and `requestFieldMapping` sources it from status instead —
  `hook_id`, `ruleset_id`, `release_id`, `runner_group_id`, `branch_policy_id`,
  `milestone_number`, `issue_number`, `team_slug`. It is the same pattern
  `PullRequest` uses for `pull_number`.
- **Static per-verb headers and queries.** `TeamRepo`'s observe sends
  `Accept: application/vnd.github.v3.repository+json`; without it GitHub answers 204 and
  there is nothing to observe. `Collaborator`'s observe pins `affiliation=direct`, the
  only view that reports the repository-level grant the CR owns rather than the user's
  effective permission. Upstream hands both jobs to a proxy plugin; a static per-verb
  value does them natively.
- **`responseTransform` jq.** `BranchProtection`'s GET answers in a different shape from
  the PUT that sets it, so one whole-document program rewrites it back into the CR
  domain at the reconcile chokepoint — `{"enabled": bool}` wrappers to bare booleans,
  restriction objects to login/slug strings, absent controls to `null`, every list
  sorted so an order-sensitive comparison is deterministic. `TeamRepo` derives the CR's
  `permission` from the observed cumulative `permissions` booleans, which is what makes
  the grant observable at all.
- **`notFoundBody` predicates.** `Workflow` and `AutomatedSecurityFixes` answer 200
  whether the thing is on or off, so absence has to be defined on the body:
  `.enabled == false` for the security-fixes toggle, a `disabled_manually` /
  `disabled_inactivity` / `deleted` state for a workflow. The controller then re-runs
  create — which is exactly what switches the feature back on. Without the predicate the
  CR would report Available while the feature was off.
- **`findby`.** `Collaborator` observes over the collaborator list, because the per-user
  endpoints return either no body (204/404) or the user's *effective* permission, which
  would make any org member read back as an up-to-date collaborator.

## Why the git-write kinds need a plugin

GitHub's git-write endpoints have quirks a pure OpenAPI-to-HTTP mapping cannot express;
left alone, a `rest-dynamic-controller` observes the wrong thing, sees spurious drift,
and re-issues create/update forever — the CR never reaches Ready. The RestDefinitions
point the affected verbs at the plugin's in-cluster URL (a per-operation OpenAPI
`servers` override, resolved through `tpl` in the ConfigMaps — see
`chart/templates/_helpers.tpl`), so the controller calls the plugin for exactly those
verbs; **every other verb still goes straight to GitHub**. The plugin serves three kinds
and three only — `GitRef`, `RepoContent`, `PullRequest` — so 28 of the 31 kinds never
touch it. The plugin (`plugin/main.go`) fixes:

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

## Where the coverage stops

- **Secrets are absent, deliberately.** GitHub's Actions, Dependabot and Codespaces
  secrets take an `encrypted_value` — a LibSodium sealed box — together with the
  `key_id` of the repository or organization public key. Producing one means fetching
  that key first and then encrypting client-side, and a RestDefinition expresses neither
  a prior fetch nor client-side crypto. Those kinds are therefore not expressible at
  all, rather than merely unimplemented. **Variables are not secrets**:
  `ActionsVariableRepo`, `ActionsVariableOrg` and `EnvironmentVariable` cover the
  plaintext half of the same surface.
- **`VulnerabilityAlerts` was evaluated and dropped.**
  `GET /repos/{owner}/{repo}/vulnerability-alerts` returns 404 when the feature is off
  and **204 with no body** when it is on — it never returns a body, so no status schema
  can be derived from it and there is nothing for a `notFoundBody` predicate to read.
  `AutomatedSecurityFixes` is the same shape of toggle and IS covered for exactly that
  reason: its GET does return a body (`enabled`, `paused`). The difference is the body,
  not the feature.
- **`POST /user/repos`** is not modelled — see [Where Repository sits](#where-repository-sits).
- **`Issue` and `PullRequest` have no delete verb.** GitHub's REST API has no endpoint
  that deletes either (only the GraphQL `deleteIssue` mutation, which a RestDefinition
  cannot reach). Deleting such a CR stops Krateo managing the object; the issue or PR
  stays on GitHub. To close an issue, set `spec.state: closed` (optionally with
  `spec.state_reason`) and let the update verb run, then delete the CR if you no longer
  want it tracked.

## Limitations worth knowing

Per-kind consequences that are properties of GitHub's API, not gaps in the mapping. Each
is argued in full in the RestDefinition and the OpenAPI asset for that kind.

| kind | limitation |
|---|---|
| `Collaborator` | GitHub reports `role_name` as the *highest* role across repository, team, org and enterprise grants, and exposes no way to read the repository-level grant alone. If a user's effective role exceeds `spec.permission`, observe reports the higher role and the PUT re-applies the grant it already set — one findby + one PUT every reconcile, indefinitely. Grant at or above what the user already holds through the org or a team. Separately, a PUT for a non-org-member creates an *invitation*, and an invitee is not a collaborator until they accept, so such a CR stays not-Ready meanwhile. |
| `Label` | Rename is not supported: GitHub renames a label by PATCHing `new_name` while the path still addresses the current name, which needs two names in one CR field. Changing `spec.name` creates a *second* label and leaves the first behind, untracked. To rename, delete the CR and create a new one. |
| `Milestone` | `due_on` is create-only. GitHub keeps the day, discards the time, and re-times it to midnight in the token account's timezone before echoing it back in UTC — for a positive UTC offset not even the date survives — so no CR value reliably equals the GET. The stored value is surfaced as `status.due_on`. |
| `Environment` | `wait_timer`, `prevent_self_review` and `reviewers` are settable but not observable: GitHub nests them under the `protection_rules` array rather than returning them top-level. They cannot loop (the comparison skips a spec key the response omits), but a UI edit to those three is not reverted. `deployment_branch_policy` IS returned top-level and is genuinely reconciled. |
| `RepoWebhook`, `OrgWebhook` | GitHub echoes `config.secret` as the literal `********`, so the secret is deliberately excluded from the compared set — it could never match. It is still *sent* on every update, because the request body is assembled by top-level key and carries the whole `config` map; a PATCH omitting it would silently remove the webhook's HMAC signing. |
| `RepoRuleset`, `OrgRuleset` | `rules` and `bypass_actors` are arrays and the comparison is order-sensitive within an array — list them in a stable order. Extra keys GitHub fills into a rule's `parameters` are ignored, so a partially-specified rule does not read as drift. |
| `DeploymentBranchPolicy` | `type` (`branch` vs `tag`) is create-only: GitHub cannot move a policy between the two, and the update body carries only `name`. Renaming the pattern stays reconciled; the stored type is visible as `status.type`. |
| `Workflow` | Create enables and delete disables — neither creates or removes the workflow file, which only a commit under `.github/workflows` can do. A CR pointing at a missing or deleted file stays NotReady on the 404 from enable, which is the honest outcome. A fork whose workflows GitHub disables by policy (`disabled_fork`) is not treated as absent. |
| `Deployment` | Immutable by the API's own design (create/read/delete, no PATCH). Editing a `Deployment` CR's spec is not an update — it is a request for a *new* deployment, and should be a new CR. |
| `DeployKey`, `Autolink` | Immutable upstream: editing the CR cannot be pushed. `Autolink` reports the difference as drift so the operator sees it (delete and recreate); `DeployKey` does not compare its spec at all, because the only comparable field is the SSH public key and an unfixable mismatch would park every key in the fleet permanently Unavailable. |

## Trust boundary

The chart holds no secret. The GitHub token lives in a `Secret` provisioned
out-of-band; each `<Kind>Configuration` points at it; each resource CR references a
Configuration via `spec.configurationRef.name`. The Krateo portal write-path only ever
**references** these Configuration CRs — it never creates them or the Secret, and the
token is never handled by the browser or snowplow ([usage](./usage.md)).

One PAT can drive the whole chart. Each of the 31 kinds gets its own
`<Kind>Configuration`, but they may all carry the same name — `chart/samples/`
ships all 31 as `github-blueprints-config` — so a single token Secret backs every kind
in use. What that token must be allowed to do differs by kind, and the union is wider
than it used to be:

- the git-write kinds (`RepoContent`, `GitRef`, `PullRequest`) need only
  contents/refs/pulls write;
- `Repository` needs repo creation in the org — classic `repo`, or the fine-grained org
  permission **Administration: read & write**;
- the org-scoped kinds — everything addressing `/orgs/{org}/…`: `Team`, `TeamRepo`,
  `TeamMembership`, `OrgMembership`, `OrgRuleset`, `OrgWebhook`, `ActionsVariableOrg`,
  `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` — act on the organization
  itself and need organization administration rights.

Scoping the token to the kinds actually in use is the tighter arrangement; nothing in
the chart requires one token for everything ([usage](./usage.md)).

## What has been verified

Stated plainly, because the difference matters:

- `helm lint` is clean and all 31 kinds render.
- Every RestDefinition path + method was cross-checked against the operations declared
  in its own OpenAPI asset — zero mismatches.
- All 31 RestDefinitions were accepted by the **deployed**
  `restdefinitions.ogen.krateo.io` CRD at oasgen-provider 0.23.0, via
  `kubectl apply --dry-run=server` under throwaway names, confirmed absent afterwards.
- **There has been no end-to-end run against GitHub for any kind.** Where a behaviour
  above is described as verified live (`AutomatedSecurityFixes` answering 200 with
  `enabled: false`, `OrgMembership`'s real 404, `TeamRepo`'s Accept header), that
  verification was of the GitHub endpoint itself, not of a reconciling CR.
