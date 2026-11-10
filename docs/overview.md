---
type: Architecture
title: github-provider-kog — overview
description: What the chart ships and how it works — 32 RestDefinitions plus trimmed OpenAPI specs that oasgen-provider turns into github.krateo.io CRDs and a controller per kind, how each kind decides drift via compareScope, what keeps every one of the 32 native, and why the chart ships no runtime component of its own.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, kog, oasgen-provider, rest-dynamic-controller, github]
timestamp: 2026-09-09T00:00:00Z
---

# Overview

github-provider-kog exposes 32 GitHub REST resources as `github.krateo.io` Kubernetes
kinds. It ships **no controller of its own** for any of them — it declares the API
mapping and lets `oasgen-provider` generate the CRDs and spawn a
`rest-dynamic-controller` per kind. Every one of the 32 calls `api.github.com` directly:
there is no proxy, no plugin, no image. The chart is RestDefinitions and OpenAPI
documents, and nothing else.

## What the chart covers

Six groups. Each row is one kind, its primary endpoint, and what a CR of it expresses;
the per-verb tables live in [configuration](./configuration.md) and the generated fields
in [api](./api.md).

### Repository

| Kind | GitHub API | What a CR expresses |
|------|-----------|---------------------|
| `Repository` | `POST /orgs/{org}/repos` | the destination repository (org-owned) |
| `UserRepository` | `POST /user/repos` | the destination repository, owned by the token's own user account rather than an org |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | a branch or tag ref; the base sha is resolved from the default branch when `sha` is omitted |

`RepoContent` was here too; it, `PullRequest` (now under
[Work tracking](#work-tracking)) and `GitRef` returned natively — see
[what the git-write kinds were, and where their design lives](#what-the-git-write-kinds-were-and-where-their-design-lives).

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
| `Issue` | `POST /repos/{owner}/{repo}/issues` | an issue — title and body reconciled; open/closed is read-only (below) |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | a pull request from a head branch into a base branch |
| `Release` | `POST /repos/{owner}/{repo}/releases` | a release |
| `RepoDeployment` | `POST /repos/{owner}/{repo}/deployments` | an immutable deployment record |

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

All 32 ConfigMaps are a plain `.Files.Get`: every kind is native, so its asset is copied
into the ConfigMap verbatim and contains no template action.

That is the whole render — 32 ConfigMaps and 32 RestDefinitions. **The chart ships no
runtime component**: no `Deployment`, no `Service`, no image, nothing that has to be
built or pulled. The only workloads in play are the `rest-dynamic-controller`s
oasgen-provider deploys per kind, which are not this chart's.

Every generated CRD lands under `resourceGroup` (default `github.krateo.io`), the
chart's `resourceGroup` value ([configuration](./configuration.md)). All 32 kinds render
by default, and `kinds` narrows that to a chosen list.

**Size for one pod per kind, plus one.** Each RestDefinition runs one
`rest-dynamic-controller` pod, whether or not a CR of its kind exists, and the composition
adds its own controller pod: 33 pods by default. On krateo-057, 32 controllers run while
only `Repository` and `PullRequest` have resource CRs. A namespace pod quota counts all of
them, and a controller the quota refuses leaves its kind with a CRD that nothing
reconciles. With `kinds: [Repository, PullRequest]` the provider needs 3 pods.

## How oasgen-provider turns this into live kinds

`oasgen-provider` (installed cluster-wide) watches the 32 `RestDefinition`s. For each it:

1. reads the referenced OpenAPI ConfigMap (`configmap://<ns>/<name>/<file>`),
2. generates the CRD under `github.krateo.io`, unioning the request fields across the
   mapped verbs into the CRD's `spec`, and
3. **auto-deploys a `rest-dynamic-controller` Deployment per kind**, which reconciles
   each CR by calling the mapped HTTP verbs (create/get/update/delete).

The required version is **≥ 0.38.0**: 0.38.0 is where the `GitRef` pattern admission guard
reaches the generated CRD. `GitRef`'s create resolves its base sha with a
`dependentLookups` chain, a primitive that landed in 0.36.0. The earlier
floor was 0.23.0 — 25 of the 32 RestDefinitions declare `compareScope: updatable`, the
field 0.23.0 added — and that requirement still holds, now subsumed by 0.38.0.

Because every RestDefinition's OpenAPI declares a bearer `securityScheme`,
oasgen-provider also generates a per-kind **`<Kind>Configuration`** CRD — 32 of them,
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
| `updatable` | the other 25 | compares exactly what the update body can express, derived from the OAS. **Load-bearing** where the response carries a key the update cannot fix — `TeamRepo`'s `owner`, `Issue`'s `labels`, `Milestone`'s `due_on`, the webhooks' `config.secret`, `Collaborator`'s effective `role_name`. **Defensive** on the rest, whose only surplus `fullSpec` keys are create-only fields or path parameters: the response omits those, the comparison skips them, and the two scopes agree today. Requires an update verb, and oasgen-provider ≥ 0.23.0. |
| `fullSpec` (left unset, 3) | `Workflow`, `AutomatedSecurityFixes`, `RepoContent` | `Workflow` and `AutomatedSecurityFixes` have no update verb at all, so `updatable` is unavailable — but their specs hold nothing except path parameters, which the response does not carry, and the comparison skips a spec key absent from the response, so fullSpec compares nothing and cannot report false drift; the drift that matters is caught by a `notFoundBody` predicate instead. `RepoContent` *does* have update and delete verbs, but keeps the default deliberately: the only spec keys its get response echoes are `content` and an optional `sha`, so fullSpec compares exactly what the kind manages and `updatable` would derive the same set. |
| `fullSpec` (set explicitly, 1) | `Autolink` | also has no update verb, and here fullSpec is the point rather than a fallback: the GET returns the whole resource, so a synced autolink never drifts, and an edited CR *should* report drift — an autolink is immutable, and the operator has to delete and recreate it. `identifiersAndStatus` would report Ready while the spec and the repository disagreed. |
| `identifiersAndStatus` (3) | `DeployKey`, `RepoDeployment`, `GitRef` | `DeployKey` and `RepoDeployment` have no update verb either, so `updatable` is unavailable — but unlike `Autolink` they carry spec fields fullSpec would compare and nothing could fix: a multi-line SSH public key whose byte-identical echo cannot be verified read-only; a deployment's `environment`, which a CI job posting a deployment status can rewrite. (Their create-only fields — `auto_merge`, `required_contexts` — are absent from the response and skipped either way.) The status list is chosen so the compared set contains no spec field at all: the resource exists, therefore it is up to date — the honest model of an immutable record, and a deleted one is still detected, because the GET 404s and the controller recreates it. `GitRef` reaches the same empty projected set from the other direction: it *has* update and delete verbs, but its one identifier `ref` is also its only compared key — a tautology, since observe found the ref *by* that ref — and the create-time base `sha` is kept out of desired state structurally, so the drift that matters is the observe 404, not a body compare. |

The reasoning for each setting is written in the RestDefinition that carries it
(`chart/templates/rd-<kind>.yaml`), next to the line it justifies.

## Where Repository sits

`Repository` is the one kind in the chart that brings a resource into being rather than
configuring one that already exists: every other kind addresses a repository, an
environment or an organization that is already there. It is also what makes the rest of
the set self-sufficient — a composition can declare the repository and then its webhooks,
environments, rulesets, branch protection and team grants as CRs in the same apply, with
no hand-created destination in front of them.

Four things about the mapping are worth stating plainly:

- **Every verb is native.** create `POST /orgs/{org}/repos`; get, update and delete
  `GET` / `PATCH` / `DELETE /repos/{org}/{name}`. **Deleting the CR deletes the repository**, as
  GitHub's API defines; annotate the CR `krateo.io/deletion-policy: orphan` to keep it
  ([usage](./usage.md#keeping-a-repository-when-its-cr-is-deleted)). The verb was left out until
  oasgen-provider #125 was fixed: oasgen used to drop a RestDefinition's CRD unconditionally,
  which would have deleted every repository the kind created; it now refuses while instances
  exist. All go straight to `api.github.com`, as every verb of every kind here does.
- **`compareScope: updatable`, not the default `fullSpec` — defensively.** It compares
  exactly the fields the PATCH body can express. The three create-only fields
  (`auto_init`, `gitignore_template`, `license_template`) are never echoed on GET, so the
  comparison skips them under either scope and they cannot loop; every spec field the GET
  *does* echo is in the PATCH body, so the two scopes agree today. `updatable` is set
  because it states the intent explicitly and stays correct if a non-updatable field is
  added later. It requires an update verb, which this resource has, and needs
  oasgen-provider **0.23.0** or newer ([configuration](./configuration.md)).
- **`auto_init` defaults to true, and it is load-bearing.** A repository created with
  `auto_init=false` has no commit and therefore no default branch, so anything that
  addresses a branch of it fails until someone pushes by hand — a `BranchProtection` CR
  naming `main`, an `Environment` branch policy, or a git write arriving over
  `git-provider`.
- **The path parameters are `org` and `name`, not GitHub's `owner`/`repo`.**
  Deliberate: the same two CR fields then serve the create path
  (`/orgs/{org}/repos`), the create body (`name`) and the get/update/delete path
  (`/repos/{org}/{name}`), so the generated CRD carries one pair of fields instead of
  an `org`/`owner` duplicate the author has to keep in sync.

GitHub's second create endpoint, **`POST /user/repos`** (user-owned repositories), is
modelled by a separate kind, **`UserRepository`** — a RestDefinition has a single create
verb and cannot choose between two paths at runtime, so the user-owned create is its own
kind rather than a mode of this one. Krateo destinations are normally org-owned;
`UserRepository` is for the case where the destination belongs to the token's own account.

## What keeps all 32 kinds native

Not one of them has a hop in front of `api.github.com`. That is possible because a
RestDefinition expresses more than a path table, and the quirks that would otherwise
need a proxy are handled at the mapping layer:

- **Server-assigned identifiers.** An id the author cannot know is a path parameter on the item
  verbs only, and `requestFieldMapping` sources it from status. oasgen omits a mapped parameter
  from the spec entirely —
  `hook_id`, `ruleset_id`, `release_id`, `runner_group_id`, `branch_policy_id`,
  `milestone_number`, `issue_number`, `team_slug`. The matching `excludedSpecFields` entry is a
  redundant no-op kept for immutability (#290).
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

## What the git-write kinds were, and where their design lives

`RepoContent`, `GitRef` and `PullRequest` served the legacy blueprint-publish path: the
Autopilot builder wrote a chart tree into a repository as `github.krateo.io` CRs
(`Repository` → `GitRef` → `RepoContent` per file → `PullRequest`). The frontend now
defaults to an SCM-agnostic route instead — `AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults
to `"true"` in the frontend chart's `values.yaml` **and** its `values.schema.json`, so a
fresh install publishes through a `BuilderPublish` claim over `git-provider`, and the
`github.krateo.io` route is explicitly the `"false"` fallback.

They were also the only three kinds that needed the companion proxy plugin. GitHub's
git-write endpoints have quirks a pure OpenAPI-to-HTTP mapping could not express at the
time, and the plugin normalized them: resolving the default-branch HEAD sha for a
sha-less `GitRef` create, bridging GitHub's `git/ref` (read) vs `git/refs` (write) path
asymmetry, making `RepoContent`'s PUT an idempotent create-or-update and canonicalizing
its base64, and flattening `PullRequest`'s `head`/`base` objects to their `ref` strings.
Removing the three kinds and the plugin together is what left the chart with no runtime
component at all — and `RepoContent`, `PullRequest` and `GitRef` have since come back
**natively**, still without it.

The knowledge did not go with the code. One design document per kind records what the
plugin handler did, why, and exactly what it took (or would take) to bring that kind back
**natively**:

- [design-repocontent](./design-repocontent.md) — **returned.**
  `status.sha` auto-populates the update body (proven by the delete verb, which was always
  native), so the 422-then-retry is not needed; the rest is a `responseTransform` on
  get/create/update plus a `fieldMapping` for `branch` → `?ref`. The `%252F` double-escape
  that broke observe on a `builder/x` branch is fixed upstream in 0.23.0.
- [design-pullrequest](./design-pullrequest.md) — **returned.** One whole-document
  `responseTransform` on the get verb replaces the head/base flattening, with
  `compareScope: updatable` alongside it to drop the create-only fields from the compared
  set.
- [design-gitref](./design-gitref.md) — **returned.** Resolving the base HEAD sha when the
  CR omits `sha` is a pre-call dependent read a RestDefinition could not express — tracked
  as oasgen-provider **#120** — and it shipped as `dependentLookups` in **0.36.0**, so a
  sha-less create is native and `spec.sha` stays optional. A `requestTransform` adds the
  `refs/` prefix the create-ref body wants onto the short-form `spec.ref`.

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
- **`POST /user/repos` is no longer absent** — it is modelled by the separate
  `UserRepository` kind; see [Where Repository sits](#where-repository-sits).
- **The git-write kinds have all returned natively.** Committing a file into a
  repository (`RepoContent`), creating a branch or tag (`GitRef`) and opening a pull
  request (`PullRequest`) left with the proxy plugin, and all three have come back
  natively. The portal still publishes over `git-provider` by default. What each native
  restoration took is written down ([above](#what-the-git-write-kinds-were-and-where-their-design-lives)).
- **`PullRequest` has no delete verb and cannot be closed from its spec.** `state` is in the
  PATCH body but not the create body, so it never becomes a spec field. Merge or close the PR
  on GitHub, then delete the CR.
- **`Issue` has no delete verb.** GitHub's REST API has no endpoint that deletes an issue
  (only the GraphQL `deleteIssue` mutation, which a RestDefinition cannot reach).
  Deleting such a CR stops Krateo managing the object; the issue stays on GitHub. As with
  `PullRequest`, `state` is in the PATCH body but not the create body, so it never becomes
  a spec field and an issue cannot be closed from its CR. Close it on GitHub, then delete
  the CR if you no longer want it tracked; `status.state` shows which it is.

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
| `RepoDeployment` | Immutable by the API's own design (create/read/delete, no PATCH). Editing a `RepoDeployment` CR's spec is not an update — it is a request for a *new* deployment, and should be a new CR. |
| `DeployKey`, `Autolink` | Immutable upstream: editing the CR cannot be pushed. `Autolink` reports the difference as drift so the operator sees it (delete and recreate); `DeployKey` does not compare its spec at all, because the only comparable field is the SSH public key and an unfixable mismatch would park every key in the fleet permanently Unavailable. |

## Trust boundary

The chart holds no secret. The GitHub token lives in a `Secret` provisioned
out-of-band; each `<Kind>Configuration` points at it; each resource CR references a
Configuration via `spec.configurationRef.name`. The Krateo portal write-path only ever
**references** these Configuration CRs — it never creates them or the Secret, and the
token is never handled by the browser or snowplow ([usage](./usage.md)).

One PAT can drive the whole chart. Each of the 32 kinds gets its own
`<Kind>Configuration`, but they may all carry the same name — `chart/samples/`
ships 31 of the 32 as `github-blueprints-config` — so a single token Secret backs every kind
in use except `UserRepository`, which creates repositories in the token's own account and so
gets its own Configuration carrying the intended user's token. What that token must be allowed to do differs by kind:

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

- `helm lint` is clean and all 32 kinds render by default — 32 ConfigMaps + 32 RestDefinitions and
  nothing else, with zero plugin references anywhere in the rendered output.
- Every RestDefinition path + method was cross-checked against the operations declared
  in its own OpenAPI asset — zero mismatches.
- The original 29 RestDefinitions were accepted by the **deployed**
  `restdefinitions.ogen.krateo.io` CRD at oasgen-provider 0.23.0, via
  `kubectl apply --dry-run=server` under throwaway names, confirmed absent afterwards;
  `GitRef`, the 30th, is cross-checked the same way.
- **There has been no end-to-end run against GitHub for any kind.** Where a behaviour
  above is described as verified live (`AutomatedSecurityFixes` answering 200 with
  `enabled: false`, `OrgMembership`'s real 404, `TeamRepo`'s Accept header), that
  verification was of the GitHub endpoint itself, not of a reconciling CR.
