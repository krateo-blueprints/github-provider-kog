---
type: API
title: github-provider-kog — API
description: The CRDs this component brings into the cluster — the 32 resource kinds under github.krateo.io, all of them native, grouped by area, with their paths, identifiers, status fields and compareScope, the oasgen-generated <Kind>Configuration kind each one gets, and the CompositionDefinition the core-provider CDC derives from values.schema.json.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, crd, compositiondefinition, github, oasgen-provider]
timestamp: 2026-09-09T00:00:00Z
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
  name: github-provider-kog
  namespace: krateo-system
spec:
  chart:
    url: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
    version: <released version>
```

From `chart/Chart.yaml`, core-provider derives the generated composition API: **Kind**
from `name` (dashes dropped, CamelCased → `KrateoGithubProviderKog`) and **apiVersion**
from `version` (`X.Y.Z` → `composition.krateo.io/vX-Y-Z`). The composition's `spec` is
typed by `values.schema.json`, whose only knob is the scalar `resourceGroup`
([configuration](./configuration.md)).

## The generated `github.krateo.io` kinds

oasgen-provider watches the **32** `RestDefinition`s and generates the CRDs below under
`resourceGroup` (default `github.krateo.io`, group version `v1alpha1`), auto-deploying a
`rest-dynamic-controller` per kind. Every resource CR carries a `spec.configurationRef`
(added by oasgen from the OpenAPI `securityScheme`) naming the `<Kind>Configuration` that
holds its token wiring.

**oasgen-provider ≥ 0.38.0 is required.** 0.38.0 is where the `GitRef` pattern admission
guard reaches the generated CRD ([#249](https://github.com/krateo-platformops/oasgen-provider/issues/249)/#250);
`GitRef`'s create resolves its base sha with a `dependentLookups` chain that landed in
0.36.0; the `compareScope: updatable` that 25 of the 32 kinds declare needs ≥ 0.23.0, a
floor now subsumed by 0.38.0 ([configuration](./configuration.md)).

**All 32 kinds are native.** Every verb goes straight to `api.github.com`, and the
normalizations GitHub's REST inconsistencies demand are expressed in the RestDefinition
itself (static query parameters and headers, `fieldMapping` aliases, request/response jq
transforms, `dependentLookups`, `notFoundBody` predicates). The chart ships **no runtime
component of its own**: it renders 32 ConfigMaps and 32 RestDefinitions and nothing else —
no Deployment, no Service, no image, no proxy. The only workloads involved are the
`rest-dynamic-controller` deployments oasgen-provider creates per kind.

Three kinds used to route some verbs through a companion proxy plugin — `GitRef`,
`RepoContent` and `PullRequest`. The plugin is gone, and publishing now defaults to a
`BuilderPublish` claim over `git-provider` (`AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults
to `"true"` in the frontend chart's `values.yaml` and `values.schema.json`), so the
`github.krateo.io` route is the `"false"` fallback. All three have since
returned natively, without the plugin — `GitRef` via a create `requestTransform` for the
`refs/` prefix and a `dependentLookups` chain for the base sha, `PullRequest` via a
`responseTransform` flattening `head`/`base`, and `RepoContent` via a `responseTransform`
plus `status.sha` auto-populating the update body. What each
kind did, and what its native restoration took, is recorded in
[design-gitref](./design-gitref.md), [design-repocontent](./design-repocontent.md) and
[design-pullrequest](./design-pullrequest.md).

### The kind set at a glance

One row per kind: the verbs and their paths, the `identifiers` the RestDefinition
declares, the `compareScope`, and the `additionalStatusFields` that land under `status`.
`configurationFields` is empty on all 32 — the token wiring comes from the
`<Kind>Configuration`, never from spec fields. The kinds with a trap worth reading before
authoring one are written out in full below the tables.

**Access** — who can reach what.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `Team` | create `POST /orgs/{org}/teams`; get/update/delete `GET`/`PATCH`/`DELETE /orgs/{org}/teams/{team_slug}` | `slug` | `updatable` | `id`, `node_id`, `html_url` |
| `TeamRepo` | create/update `PUT`, get `GET`, delete `DELETE` on `/orgs/{org}/teams/{team_slug}/repos/{owner}/{repo}` | `full_name` | `updatable` | `id`, `html_url`, `role_name` |
| `TeamMembership` | create/update `PUT`, get `GET`, delete `DELETE` on `/orgs/{org}/teams/{team_slug}/memberships/{username}` | `url` | `updatable` | `role`, `state` |
| `Collaborator` | create/update `PUT /repos/{owner}/{repo}/collaborators/{login}`; **findby** `GET /repos/{owner}/{repo}/collaborators`; delete `DELETE` on the item path | `login` | `updatable` | `role_name` |
| `OrgMembership` | create/update `PUT`, get `GET`, delete `DELETE` on `/orgs/{org}/memberships/{username}` | `url` | `updatable` | `state`, `direct_membership` |

**Repository configuration** — how a repository or org is set up.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `RepoWebhook` | create `POST /repos/{owner}/{repo}/hooks`; get/update/delete `GET`/`PATCH`/`DELETE .../hooks/{hook_id}` | `id` | `updatable` | `url`, `ping_url`, `deliveries_url`, `created_at`, `updated_at` |
| `OrgWebhook` | create `POST /orgs/{org}/hooks`; get/update/delete `GET`/`PATCH`/`DELETE .../hooks/{hook_id}` | `id` | `updatable` | `url`, `ping_url`, `deliveries_url`, `created_at`, `updated_at` |
| `DeployKey` | create `POST /repos/{owner}/{repo}/keys`; get/delete `GET`/`DELETE .../keys/{key_id}` — **no update verb** | `id` | `identifiersAndStatus` | `url`, `verified`, `created_at` |
| `Environment` | create/update `PUT`, get `GET`, delete `DELETE` on `/repos/{owner}/{repo}/environments/{environment_name}` | `name` | `updatable` | `id`, `node_id`, `html_url`, `created_at`, `updated_at` |
| `RepoRuleset` | create `POST /repos/{owner}/{repo}/rulesets`; get/update/delete `GET`/`PUT`/`DELETE .../rulesets/{ruleset_id}` | `id` | `updatable` | `node_id`, `name`, `target`, `source_type`, `source`, `enforcement`, `created_at`, `updated_at` |
| `OrgRuleset` | create `POST /orgs/{org}/rulesets`; get/update/delete `GET`/`PUT`/`DELETE .../rulesets/{ruleset_id}` | `id` | `updatable` | `node_id`, `name`, `target`, `source_type`, `source`, `enforcement`, `created_at`, `updated_at` |
| `Autolink` | create `POST /repos/{owner}/{repo}/autolinks`; get/delete `GET`/`DELETE .../autolinks/{autolink_id}` — **no update verb** | `id` | `fullSpec` (set explicitly) | — |
| `BranchProtection` | create/update `PUT`, get `GET`, delete `DELETE` on `/repos/{owner}/{repo}/branches/{branch}/protection` | `url` | `updatable` | — |
| `GitRef` | create `POST /repos/{owner}/{repo}/git/refs`; get `GET .../git/ref/{ref}`; update/delete `PATCH`/`DELETE .../git/refs/{ref}` | `ref` | `identifiersAndStatus` | `node_id`, `url`, `object.sha` |

**CI/CD** — Actions configuration and deployment gating.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `ActionsVariableRepo` | create `POST /repos/{owner}/{repo}/actions/variables`; get/update/delete `GET`/`PATCH`/`DELETE .../variables/{name}` | `name` | `updatable` | `created_at`, `updated_at` |
| `ActionsVariableOrg` | create `POST /orgs/{org}/actions/variables`; get/update/delete `GET`/`PATCH`/`DELETE .../variables/{name}` | `name` | `updatable` | `created_at`, `updated_at`, `selected_repositories_url` |
| `EnvironmentVariable` | create `POST /repos/{owner}/{repo}/environments/{environment_name}/variables`; get/update/delete `GET`/`PATCH`/`DELETE .../variables/{name}` | `name` | `updatable` | `created_at`, `updated_at` |
| `RunnerGroup` | create `POST /orgs/{org}/actions/runner-groups`; get/update/delete `GET`/`PATCH`/`DELETE .../runner-groups/{runner_group_id}` | `id` | `updatable` | `id`, `default`, `inherited`, `runners_url`, `hosted_runners_url`, `selected_repositories_url` |
| `DeploymentBranchPolicy` | create `POST /repos/{owner}/{repo}/environments/{environment_name}/deployment-branch-policies`; get/update/delete `GET`/`PUT`/`DELETE .../{branch_policy_id}` | `id` | `updatable` | `node_id`, `name`, `type` |
| `Workflow` | create `PUT .../actions/workflows/{workflow_id}/enable`; get `GET .../actions/workflows/{workflow_id}`; delete `PUT .../actions/workflows/{workflow_id}/disable` | `id` | default `fullSpec` | `name`, `path`, `state`, `html_url`, `badge_url` |

**Work tracking** — issues, milestones, releases, deployments.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `Label` | create `POST /repos/{owner}/{repo}/labels`; get/update/delete `GET`/`PATCH`/`DELETE .../labels/{name}` | `name` | `updatable` | `id`, `node_id`, `url`, `default` |
| `Milestone` | create `POST /repos/{owner}/{repo}/milestones`; get/update/delete `GET`/`PATCH`/`DELETE .../milestones/{milestone_number}` | `number` | `updatable` | `number`, `id`, `node_id`, `html_url`, `state`, `due_on`, `open_issues`, `closed_issues` |
| `Issue` | create `POST /repos/{owner}/{repo}/issues`; get/update `GET`/`PATCH .../issues/{issue_number}` — **no delete verb** | `number` | `updatable` | `number`, `id`, `node_id`, `html_url`, `state`, `comments` |
| `PullRequest` | create `POST /repos/{owner}/{repo}/pulls`; get/update `GET`/`PATCH .../pulls/{pull_number}` — **no delete verb**; the get verb carries a `responseTransform` | `number` | `updatable` | `number`, `html_url`, `state` |
| `Release` | create `POST /repos/{owner}/{repo}/releases`; get/update/delete `GET`/`PATCH`/`DELETE .../releases/{release_id}` | `id` | `updatable` | `node_id`, `html_url`, `upload_url`, `created_at` |
| `RepoDeployment` | create `POST /repos/{owner}/{repo}/deployments`; get/delete `GET`/`DELETE .../deployments/{deployment_id}` — **no update verb** | `id` | `identifiersAndStatus` | `node_id`, `sha`, `url`, `statuses_url`, `original_environment`, `created_at` |
| `RepoContent` | create/update `PUT /repos/{owner}/{repo}/contents/{path}`; get `GET` same path (`?ref` ← `spec.branch`); delete `DELETE` same path | `path` | default `fullSpec` | `sha`, `html_url` |

**Governance** — org-level policy.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `CustomProperty` | create/update `PUT`, get `GET`, delete `DELETE` on `/orgs/{org}/properties/schema/{property_name}` | `property_name` | `updatable` | `source_type`, `url` |
| `CodeSecurityConfig` | create `POST /orgs/{org}/code-security/configurations`; get/update/delete `GET`/`PATCH`/`DELETE .../configurations/{configuration_id}` | `id` | `updatable` | `target_type`, `html_url`, `created_at` |
| `AutomatedSecurityFixes` | create `PUT`, get `GET`, delete `DELETE` on `/repos/{owner}/{repo}/automated-security-fixes` | *(none — a singleton toggle)* | default `fullSpec` | `enabled`, `paused` |

**Repository creation** — the destination repository itself, written out in full below.

| kind | verbs | identifiers | `compareScope` | status |
|---|---|---|---|---|
| `Repository` | create `POST /orgs/{org}/repos`; get/update `GET`/`PATCH /repos/{org}/{name}` with `name` from `status.name` (the name GitHub assigned). **No delete verb** — deleting the CR orphans the repository, it does not destroy it (see below) | `name` | `updatable` | `id`, `node_id`, `full_name`, `html_url`, `clone_url`, `ssh_url`, `default_branch` |
| `UserRepository` | create `POST /user/repos`; get/update `GET`/`PATCH /repos/{owner}/{name}` with `owner` from `status.owner.login` and `name` from `status.name`; **findby** `GET /user/repos?affiliation=owner` (paginated) before status exists — **no delete verb** | `name` | `updatable` | `owner.login`, `id`, `node_id`, `full_name`, `html_url`, `clone_url`, `ssh_url`, `default_branch` |

### `Repository` — create the destination repository

| field | type | notes |
|---|---|---|
| `spec.configurationRef.name` | string | the `RepositoryConfiguration` to authenticate with |
| `spec.org` | string | the organization — a path param on every verb |
| `spec.name` | string | the repository name — the identifier, and the only required create-body field |
| `spec.description` / `spec.homepage` | string | repository metadata |
| `spec.private` | boolean | **create-only** — honoured at create, never reconciled; see below |
| `spec.visibility` | string | **create-only**, same reason; the asset declares no enum, so GitHub validates it |
| `spec.has_issues` / `spec.has_wiki` / `spec.has_projects` | boolean | feature toggles |
| `spec.auto_init` | boolean | **default `true`** — create-only; see below |
| `spec.gitignore_template` / `spec.license_template` | string | create-only |
| `status.id` / `status.node_id` / `status.full_name` / `status.html_url` | | observed after create |
| `status.clone_url` / `status.ssh_url` / `status.default_branch` | string | what a git-write path or a CI job needs to reach the repo |

Verbs: create on `/orgs/{org}/repos`, get/update on `/repos/{org}/{name}`. There is no
delete verb.

`spec` is the **create** request body plus the path/query params — *not* the union of
both bodies. oasgen-provider builds it from the create action alone
(`getBaseSchemaForSpec` hardcodes it) and then adds parameters. Two consequences worth
stating, because both have been got wrong here before: `default_branch` and `archived`
live in the PATCH body only, so they are **not** spec fields and cannot be set on the CR
at all; and removing a field from the PATCH body does not remove it from the CRD, which
is exactly what makes "create-only" expressible.

The path parameters are named `org` and `name`, not GitHub's `owner`/`repo`, on
purpose: the same two CR fields then serve the create path (`/orgs/{org}/repos`), the
create body (`name`) and the get/update path (`/repos/{org}/{name}`), so the
generated CRD carries **one** pair of fields instead of an `org`/`owner` duplicate the
author has to keep in sync ([configuration](./configuration.md)).

The get/update path parameter `name` is sourced from **`status.name`** — the name GitHub
actually assigned — not from `spec.name`, mapped `inPath: name` ← `inCustomResource:
status.name` on both verbs (the `Team` model, keyed on `status.slug`). GitHub normalises a
disallowed character in a repo name on create — `POST` body `name: "my repo"` creates the repo
`my-repo` — and a `GET /repos/{org}/my%20repo` by `spec.name` then 404s **while the repo exists**,
so the controller re-creates and loops on GitHub's 422 "name already exists". Keying the get on the
assigned name addresses the real repository instead (oasgen-provider
[#386](https://github.com/krateo-platformops/oasgen-provider/issues/386)). Before the first create
`status.name` is absent, so the parameter falls back to `spec.name` and the `GET` 404s correctly
(the repo does not exist yet) → one create → `status.name` is set → every later observe addresses
it. This is also what makes an out-of-band **rename** converge: the redirect-following `GET` reports
the new name, `status.name` tracks it, and the next observe addresses it directly. It is safe only
because `name` is out of the `PATCH` body (next paragraph): were it compared, tracking the real name
would PATCH it back to `spec.name` every reconcile.

`auto_init` defaults to `true` and is load-bearing. A repository created with
`auto_init: false` has no commit and therefore no default branch, so whatever writes
into it next — the `BuilderPublish` path over `git-provider`, a CI job, a clone — has
no base sha to branch from and nothing to commit against. `Repository` creates the
destination; the branch/file/PR steps that follow it are `GitRef` → `RepoContent` →
`PullRequest`. `GitRef`, `PullRequest` and `RepoContent` all returned natively. See
[design-gitref](./design-gitref.md),
[design-repocontent](./design-repocontent.md) and
[design-pullrequest](./design-pullrequest.md).

Drift is compared with `compareScope: updatable`, not the default `fullSpec`: exactly
the fields the `PATCH` body can express are compared, which is `description`, `homepage`,
`has_issues`, `has_wiki`, `has_projects`, `default_branch` and `archived`. Edit one of
those on an applied CR and it is pushed to GitHub.

**`private` and `visibility` are not in that set, deliberately.** They are create-body
fields the `PATCH` body omits, so they are honoured when the repository is created and
ignored from then on: flip a repository's exposure in GitHub and no reconcile reverts it.
The reason is that consumers render a `Repository` on every composition and
core-provider's default `UpgradePolicy` is `Automatic` — so while they were compared, a
consumer changing its rendered value did not only affect repositories created afterwards,
it PATCHed the ones that already existed. Exposure is the one field where that is
unrecoverable: forks, clones, caches and search indexing survive a flip back. `name` is
out of the same body for the same class of reason (it would reconcile a *rename*).

`auto_init`, `gitignore_template` and `license_template` are create-only too, but for a
different and weaker reason: GitHub never echoes them on `GET`, and the comparison skips
a spec key the response does not carry, so they could not drift under `fullSpec` either.

That difference is why **`updatable` is load-bearing on this kind, not defensive.** GitHub
*does* echo `private` and `visibility` on every `GET`, so the default `fullSpec` would
compare them straight back into the drift set even though the `PATCH` body omits them.
Setting this kind to `fullSpec` — or deleting the line, since `fullSpec` is the default —
silently restores the hazard. The rule and its code evidence are in
[configuration](./configuration.md).

GitHub's second create endpoint, `POST /user/repos` (user-owned repositories), is modelled
by a separate kind, `UserRepository` (its row is in the table above): a `RestDefinition`
has one create verb and cannot choose between two paths, so the user-owned create is its
own kind. Krateo destinations are normally org-owned.

### `Collaborator` — `status.role_name` is the effective role, and can over-report

`spec.permission` (`pull`/`triage`/`push`/`maintain`/`admin`, or a custom repository
role) is the grant this CR sets on the repository. `status.role_name` is **not** a
read-back of that grant: GitHub returns the **highest effective role** the user holds
across repository, team, organization and enterprise grants, and documents no way to
read the repository-level grant on its own.

The consequence is a **residual drift loop that no `compareScope` value fixes**. When a
user's effective role exceeds what this CR asks for — they are an org owner, or a team
grants more than `spec.permission` — observe reports the higher role, the controller
re-issues the `PUT` that sets the repository grant it already set, and the next observe
reports the higher role again: one findby plus one PUT every reconcile, indefinitely,
against a 5000 req/hr budget. Simulated against rest-dynamic-controller
(`spec.permission: push` against `role_name: admin` never converges). Grant a
collaborator at or above what they already hold through the organization or a team, or
expect the loop.

Two further properties of the observe path:

- It is a **findby** over `GET /repos/{owner}/{repo}/collaborators` pinned to
  `affiliation=direct`, not a get. `GET .../collaborators/{username}` returns 204/404
  with no body (nothing to compare or populate), and `.../permission` returns the
  *effective* permission, so any org member on a repo with a base permission would read
  back as an existing, up-to-date collaborator and the PUT would never fire.
  `affiliation=direct` is the only view that reports the repository-level grant this CR
  owns. The findby walks every page via the `pageNumber` pagination strategy (short-page
  termination), so a repository with more than 100 direct collaborators is observed in full.
- Adding a user who is **not** an organization member creates a repository
  **invitation** (201), and an invitee is not a collaborator until they accept — so the
  CR stays not-Ready and re-issues the PUT each reconcile until then. GitHub caps
  outside-collaborator invitations at 50 per repository per 24h. Org members are added
  directly (204) and appear at once, so the platform-engineering case converges on the
  first reconcile; treat the outside-collaborator case as pending.

GitHub reports `role_name` in its display vocabulary (`read`/`write`) while the PUT body
takes `pull`/`push`; a `fieldMapping` alias relocates the observed value onto
`spec.permission` so the comparison sees matching vocabulary. That fixes the vocabulary
mismatch only — never the effective-role over-report above.

### `Team` — the update answers 201, not 200

`slug`, not `name`, is a team's external identity: every item verb addresses
`/orgs/{org}/teams/{team_slug}`, GitHub derives the slug from the name, and `team_slug`
is `excludedSpecFields` and sourced from `status.slug`.

The trap is the response code. **`PATCH /orgs/{org}/teams/{team_slug}` answers `201`
when it actually changes something**, and `200` only "when the updated information
already exists" — and the controller issues an update *only* after observing drift, i.e.
exactly in the changing case. rest-dynamic-controller accepts only the 2xx codes
**declared on the operation**, so an OpenAPI document listing `200` alone would turn
every real update into `invalid status code: 201`: the CR would never converge and a
team rename would fail forever, reported as an API error. `chart/assets/team.yaml`
therefore declares both codes.

Renaming a team (editing `spec.name`) converges. The PATCH is addressed by the slug in
`status` at the time — still valid, since the rename has not happened yet — and returns
the whole team, so `status.slug` is repopulated and the next observe addresses the new
slug.

### `RepoDeployment` — `auto_merge` is pinned `false`

A deployment is an immutable historical record: GitHub's API here is create/read/delete
with **no update verb**, which is why this kind uses `compareScope:
identifiersAndStatus` — nothing else could be fixed even if it were compared. Changing a
RepoDeployment CR's spec is not an update; it is a request for a *new* deployment, and should
be a new CR.

`spec.auto_merge` defaults to **`false`** in `chart/assets/deployment.yaml`, overriding
GitHub's own default of `true`. With `auto_merge: true` and a `ref` behind the default
branch, GitHub merges instead of deploying and answers **202 with a `{"message": ...}`
body** — there is no deployment, no id, nothing for `populateStatusFields` to write to
`status.id`, and the get verb (which sources `{deployment_id}` from `status.id`) can
never address anything. The CR would sit unobservable behind a green create. Pinning the
default `false` keeps a CR that simply omits the field out of that state; set it `true`
deliberately if merge-instead-of-deploy is what you want. (Same reasoning as
`repository.yaml` pinning `auto_init`.)

`status.original_environment` is surfaced rather than `environment`, and that choice is
load-bearing under this compareScope. `identifiersAndStatus` compares identifiers plus
`additionalStatusFields`, projected onto the spec — and `environment` *is* a spec field,
so listing it would make it the one and only compared field, with no update verb to fix a
difference. That difference is not hypothetical: a CI job posting a deployment status can
rewrite the deployment's environment, which is exactly why GitHub also returns
`original_environment`. Being server-side only, it populates status without entering the
comparison, leaving the projected compared set empty — the honest reading of an immutable
record.

`spec.required_contexts` is create-time only in the same way: omit it and GitHub verifies
**all** unique commit-status contexts, answering 409 when any is failing or pending; an
empty array bypasses the check entirely. GitHub's free-form `payload` field is not
modelled — its `oneOf object|string` does not survive CRD generation as a usable field,
and the ambiguity makes the spec-vs-response comparison type-unstable.

### `Milestone` — `due_on` is create-only, because GitHub re-times it

`spec.due_on` is in the create body and **deliberately absent from the update body**.
GitHub treats a due date as a **day**, not an instant: it discards the submitted
time-of-day and stores midnight of that day **in the timezone of the account that owns
the token**, then echoes the result back in UTC. What `GET` returns therefore depends on
who called, not on what was written — and for a positive UTC offset not even the *date*
survives (an Europe/Rome token writing `2026-12-31` reads back `2026-12-30T23:00:00Z`).
Measured over ~120 dated milestones on public repositories, the echoed time-of-day flips
at the US daylight-saving boundaries within a single repository, which is what a server
converting a date to midnight in a fixed timezone does and what a client sending literal
ISO timestamps cannot produce.

So no value a CR can carry reliably equals what `GET` returns. Were `due_on` in the update
body it would be a compared field under `compareScope: updatable`, and that mismatch would
be permanent drift: a PATCH on every reconcile, forever, that "succeeds" each time — since
GitHub does store the right day — and therefore never self-corrects.

The cost is stated rather than hidden: **the due date is set once, at creation, and
editing `spec.due_on` afterwards does nothing.** That is a deterministic contract (the
field can never be sent by an update), not a knob that fires by coincidence. Write it as
`"YYYY-MM-DDT00:00:00Z"`; only the date part is honoured. Whatever GitHub actually stored
is readable on `status.due_on`. To change a due date, edit it on GitHub or recreate the
CR. `title`, `state` and `description` are in the PATCH body and are genuinely reconciled.

`number`, not `title`, identifies a milestone — GitHub allows two milestones with the same
title. `milestone_number` is `excludedSpecFields` and sourced from `status.number`.

### `BranchProtection` — the PUT body and the GET response are shaped differently

This is the one kind whose `GET` answers in a different shape from the `PUT` that sets it,
and it is handled entirely in the RestDefinition, by two jq transforms:

- **Request** (`create` and `update` are the same `PUT`): GitHub requires
  `required_status_checks`, `enforce_admins`, `required_pull_request_reviews` and
  `restrictions` to be **present even when the control is off**, and `null` is how "off"
  is spelled. A CRD field typed `object` cannot hold null (oasgen does not carry OAS
  `nullable` through), so the CR expresses "off" by omission and a `requestTransform`
  turns omission into the explicit `null` the API demands. It tests `has()` rather than
  using `//`, so a deliberate `enforce_admins: false` is not rewritten to null.
- **Response** (`get`): a whole-document `responseTransform` rewrites GitHub's answer back
  into the CR domain once, at the reconcile chokepoint, before status population and drift
  comparison — `{"enabled": bool}` wrappers flattened to bare booleans (nine controls),
  the status-check wrapper reduced to `{strict, contexts}`, `restrictions`
  users/teams/apps reduced to `login`/`slug` strings, the review object's
  `dismissal_restrictions` and `bypass_pull_request_allowances` reduced the same way, and
  an unset control (key absent) normalised to `null`, which is what the spec omitting it
  means.

Status checks are managed through `contexts` (plain check names). GitHub's newer `checks`
(`[{context, app_id}]`) form, which pins the reporting GitHub App, is **not modelled yet**:
GitHub keeps `checks` and `contexts` derived from each other, so a CR that set both would
drift-loop (GitHub derives `contexts` from the `checks` it accepts, and the derived value never
matches a different `contexts` the CR also declared), and that misconfiguration cannot be
rejected at admission — oasgen carries neither `oneOf`/`not` nor `x-kubernetes-validations` from
the asset into the generated CRD. It is held until oasgen supports admission-time cross-field
validation (CEL passthrough requested in
[oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396)); see
[configuration → Updates send whole values](./configuration.md#updates-send-whole-values--what-a-cr-owns).

The review object can carry `dismissal_restrictions` and `bypass_pull_request_allowances`
(`{users, teams, apps}` login/slug lists, org-owned repos only). Unlike the four top-level
controls, **omitting these from the review object does not clear them** — verified live on
2026-11-03, GitHub retains previously-set actors when the PUT's review object omits them. To
clear them a CR sends the object with explicit empty `users`/`teams`/`apps`; modelling them is
what lets a CR express and manage them at all. All of these are additive: a CR that sets none of
them behaves exactly as before.

Every list in that transform is **sorted**, because the comparison is order-sensitive and
GitHub does not return these in the order they were sent. Write the lists in the CR sorted
for the same reason.

`additionalStatusFields` is deliberately empty. Status is populated from the create and
update responses too, and those are **raw** — putting a flattened control in status would
force the same 30-line jq program onto all three verbs, where any divergence would make
status silently disagree with drift. The conditions already carry the signal that matters:
Available means the branch is protected exactly as the spec says. `url` is the only field
that survives the transform unchanged, which is why it is the identifier.

Because that PUT replaces the whole protection document, the CR **owns** it: a sub-control
the CR cannot express is wiped when any modelled field drifts. That is why
`required_pull_request_reviews.dismissal_restrictions` / `.bypass_pull_request_allowances`
are now **modelled** — a CR that carries them keeps them across reconciles instead of losing
them. The `required_status_checks` `checks` (`app_id`) form is still unmodelled (held, as
above). The whole-value hazard and the sub-controls still left unmodelled are in
[configuration → Updates send whole values](./configuration.md#updates-send-whole-values--what-a-cr-owns).

### Shorter caveats, by kind

- **`Label` cannot be renamed.** GitHub renames a label by PATCHing `new_name` while the
  path still addresses the *current* name — two names, which no single CR field can carry,
  and `GET` does not echo `new_name` either. Editing `spec.name` on a live CR is therefore
  **not** a rename: the next observe looks up the new name, 404s, and creates a *second*
  label, leaving the old one behind on GitHub, untracked. To rename, delete the CR (which
  deletes the label, and with it its issue associations) and create a new one.
- **`PullRequest` has no delete verb, and cannot be closed from its spec either.** GitHub's
  REST API has no endpoint that deletes a pull request. Unlike `Issue`, it also cannot close
  one: `state` lives in the PATCH body only, and the CRD spec is built from the CREATE body
  plus path/query parameters, so `state` never becomes a spec field. Merge or close the PR on
  GitHub, then delete the CR. The get verb's `responseTransform` is what makes the kind native
  — GitHub returns `head`/`base` as objects while the spec carries branch strings, and compared
  raw that is permanent drift a PATCH cannot fix (`head` is not even in the PATCH body).
- **`Issue` has no delete verb.** GitHub's REST API has no endpoint that deletes an issue
  (only the GraphQL `deleteIssue` mutation, unreachable from a RestDefinition). Deleting
  the CR only stops Krateo managing the issue; it stays where it is on GitHub. To close
  it, set `spec.state: closed` (optionally with `spec.state_reason`) and let the update
  run, then delete the CR. `spec.labels`, `spec.assignees` and `spec.milestone` are
  create-only: GitHub returns all three as
  objects where the request takes strings and an integer, so they are kept out of the
  update body and out of the comparison.
- **`Workflow` enables and disables; it does not create.** "Create" is
  `PUT .../enable` and "delete" is `PUT .../disable`, so deleting the CR undoes exactly
  what creating it did. Only a commit to `.github/workflows` creates a workflow, so a CR
  pointing at a file that does not exist stays NotReady on the 404 from enable. The
  workflow record answers 200 in every state, so a `notFoundBody` predicate reports
  `disabled_manually` / `disabled_inactivity` / `deleted` as **absent** — which is what
  makes the controller re-enable one somebody switched off in the UI. A *deleted* workflow
  can only be restored by committing the file back, which no kind in this chart does, so
  such a CR sits NotReady with a visible error, deliberately, rather than reporting
  Available. `disabled_fork` is excluded: that is repository policy, not drift, and this
  endpoint cannot clear it.
- **`AutomatedSecurityFixes` answers 200 when it is off.** A repository with the feature
  disabled returns `{"enabled": false, "paused": false}` — verified against the live API —
  not the 404 the docs suggest, so a `notFoundBody` predicate treats `enabled: false` as
  absent and the controller re-PUTs. `paused` is Dependabot's own back-off on a repo whose
  fix PRs nobody merges; the enable endpoint does not clear it, so it is surfaced on status
  and excluded from the predicate. A repository that cannot have the feature at all (plan
  or org policy) stays NotReady and retries with backoff — a real unmet declaration, made
  visible rather than hidden.
- **`DeployKey` and `Autolink` are immutable.** Neither has an update verb; changing one
  means delete and recreate, and `updatable` is unavailable to both. They then diverge on
  purpose. `Autolink`'s GET echoes its whole three-field body verbatim, so `fullSpec` is
  set explicitly and an edited CR *is* reported as drifted — correctly, because the
  operator must recreate it. `DeployKey` uses `identifiersAndStatus` so that a
  multi-hundred-character SSH public key is never compared byte-for-byte: whether GitHub
  echoes it identically (trailing newline, optional trailing comment) could not be verified
  read-only, and with no update verb any difference would park the key permanently
  Unavailable while working perfectly. Its `additionalStatusFields` are server-side facts
  only, so the compared set contains no spec field at all.
- **`Environment` has an observability gap.** `wait_timer`, `prevent_self_review` and
  `reviewers` are in the update body but absent from the top-level GET response (GitHub
  nests them under the `anyOf`-typed `protection_rules` array). The comparator ignores a
  spec key the response does not carry, so they cannot loop — they simply are not
  observed, and editing those three in the GitHub UI will not be reverted.
  `deployment_branch_policy` **is** returned top-level and is genuinely reconciled. Not
  being *compared* is not the same as being safe: because they are re-sent from spec, a PUT
  fired by `deployment_branch_policy` drift still overwrites an out-of-band value — the
  silent case in [configuration → Updates send whole values](./configuration.md#updates-send-whole-values--what-a-cr-owns).
- **`RepoRuleset` / `OrgRuleset` array order matters.** `rules` and `bypass_actors` are
  compared element-by-element, in order — list them in a stable order. Extra keys GitHub
  fills into a rule's `parameters` (defaults such as `do_not_enforce_on_create`) are
  ignored, since the comparison walks only keys the CR declares, so a partially-specified
  rule does not read as drift. **All 23 of GitHub's rule types are now modelled** — the nine
  branch-protection replacements (`creation`, `deletion`, `update`, `non_fast_forward`,
  `required_linear_history`, `required_signatures`, `pull_request`, `required_status_checks`,
  `required_deployments`), `merge_queue`, the five pattern rules (`commit_message_pattern`,
  `commit_author_email_pattern`, `committer_email_pattern`, `branch_name_pattern`,
  `tag_name_pattern`), and the remaining eight (`workflows`, `code_scanning`,
  `copilot_code_review`, `license_compliance_scanning`, `file_path_restriction`,
  `max_file_path_length`, `file_extension_restriction`, `max_file_size`). Nothing is left to
  be configured only in the UI, so an out-of-band rule is now reverted to the CR's declared
  set rather than deleted-and-unrecoverable — ordinary declarative management.
  The branch-protection set, `merge_queue` and the pattern rules were **verified live**
  2026-11-03 on a throwaway repo (since deleted): the `rules` array came back in submit
  order, enum casing was verbatim (`merge_method: SQUASH`, `grouping_strategy: HEADGREEN`, the
  operators) and pattern strings were stored exactly as sent (regex escapes included), and a
  second PUT+GET was byte-identical; the defaults GitHub fills for omitted optional keys (e.g.
  a pattern rule's `negate: false`, `name`) are response-only keys the comparator skips, so
  none loops. The five pattern rules are **not** Enterprise-gated (they worked on a Team-plan
  org). Usage notes for the eight newest types: a **`merge_queue`** rule's ruleset must target
  a concrete ref (GitHub `422`s `Wildcard ref names are not supported when merge queue is
  enabled` on a wildcard such as `~ALL`; use `refs/heads/main` or `~DEFAULT_BRANCH`); the four
  push rules (`file_path_restriction`, `max_file_path_length`, `file_extension_restriction`,
  `max_file_size`) require the ruleset's `target: push`; `workflows` and `code_scanning`
  reference another product by identifier (a workflow by `repository_id` + `path`, a tool by
  name) that the author must supply by hand.
  Six of the eight were **verified live 2026-11-04** on a **Team-plan** org (private throwaway
  repos, since deleted): `code_scanning` (`CodeQL`, `high_or_higher`, `errors`) and
  `copilot_code_review` on a branch ruleset, and all four push rules on a `push` ruleset — each
  round-tripped with order preserved and casing verbatim (e.g. `file_extension_restriction`
  kept `*.ZIP` exactly). `file_path_restriction` and `max_file_size` carry an optional
  `ignored_file_paths`, which GitHub echoes as `[]` when the CR omits it; harmless, since the
  comparison walks only the keys the CR declares.
  The other two were **rejected by GitHub on repository rulesets in a Team-plan org** (so they
  are modelled but could not round-trip there): `workflows` → `422 Invalid rule 'workflows':
  Invalid parameter workflows: Workflow error at index 0:` (empty reason; seen both without and
  with a real `.github/workflows/ci.yml` supplying a valid `repository_id`/`path`/`ref`/`sha`),
  and `license_compliance_scanning` → `422 Invalid rule 'license_compliance_scanning':` (empty
  reason). Not verified on Enterprise or at org level. They stay modelled because they are in
  GitHub's REST schema and the CR-side failure is **loud** — a `422` surfaces as `Synced=False`
  with that message — not a silent drop. The CR owns `rules` wholesale; see
  [configuration → Updates send whole
  values](./configuration.md#updates-send-whole-values--what-a-cr-owns).
- **`DeploymentBranchPolicy` cannot change `type`.** The create body is `{name, type}`;
  the update body is `{name}` alone — GitHub cannot move a policy between `branch` and
  `tag` after creation. `type` is therefore not compared (the controller could not fix it)
  and its stored value stays readable on `status.type`. Renaming the pattern is reconciled
  normally.
- **The three variable kinds cannot be renamed.** `name` is trimmed from every update
  body, because the item is *addressed* by `{name}`: a rename could never converge — the
  get would 404 at the new name and the controller would create a second variable rather
  than rename the first. Keeping `name` uncompared also neutralises GitHub's
  case-insensitive variable naming (create `my_var`, read back `MY_VAR`). `RunnerGroup` is
  the exception: it is keyed by `id`, so a rename there is a real, observable, convergent
  update.
- **Webhook secrets are never read back.** `GET .../hooks/{hook_id}` echoes
  `config.secret` as the literal `********`. Both webhook assets keep `secret` out of the
  *update body* so it is never compared, while the PATCH still **sends** it — the request
  body is assembled by top-level key, so the whole `config` map rides along. That matters:
  GitHub replaces `config` wholesale, and a PATCH omitting the secret would silently remove
  the webhook's HMAC signing. The CR is therefore **authoritative** for the secret — a value
  set out-of-band is cleared on the next `config` PATCH; see [configuration → Updates send
  whole values](./configuration.md#updates-send-whole-values--what-a-cr-owns).
- **`TeamRepo` needs a static `Accept` header to be observable at all.** Without
  `application/vnd.github.v3.repository+json` the GET answers 204 No Content; with it the
  same endpoint returns the repository object carrying the team's `permissions`, from which
  a `responseTransform` derives the CR-domain `permission` (the highest true flag — the
  booleans are cumulative). Expressing both in the RestDefinition is what keeps the kind
  native. Verified live against `api.github.com`.
- **`RunnerGroup` sets its membership only at create time.** `selected_repository_ids` and
  `runners` are create-only — GitHub's read side returns only the `*_url` links — so they
  are excluded from the comparison; manage that membership out of band via
  `status.runners_url` / `status.selected_repositories_url`.
- **`TeamMembership` and `OrgMembership` can sit `pending`.** Adding a user who is not yet
  an organization member creates an invitation, and `status.state` stays `pending` until
  they accept. It is the only way to tell a granted membership from an outstanding one.
- **`GitRef` keeps the create-time base `sha` out of the drift comparison.** `spec.ref`
  (short form `heads/<branch>` or `tags/<tag>`, pattern `^(heads|tags)/.+`) is the sole
  identifier, and `compareScope: identifiersAndStatus` projects the compared set down to
  `ref` alone — a tautology, since observe finds the ref *by* that ref. The optional
  `spec.sha` is a create-time input: when it is omitted, a `dependentLookups` chain (repo →
  `default_branch` → that branch's head) resolves the base commit, so a blueprint author
  with no sha at hand can still create `heads/<branch>`. A create `requestTransform` adds
  the `refs/` prefix GitHub's create-ref body wants onto the short-form ref; get and update
  carry the inverse `responseTransform` (`ltrimstr "refs/"`) so `status.ref` never flaps
  between forms. The declared `PATCH` never fires under this scope — force-moving a working
  branch would fight `RepoContent` on the branch `GitRef` created — but it stays declared
  because keeping it costs nothing. Needs oasgen-provider ≥ 0.36.0 for the dependent read.

### What is deliberately absent

- **Secrets — Actions, Dependabot and Codespaces.** Those endpoints require an
  `encrypted_value` (a LibSodium sealed box) plus the `key_id` of the repository or
  organization public key, which means client-side crypto and a prior fetch of that key. A
  `RestDefinition` can express neither, so those kinds are **not expressible** and are not
  shipped. **Variables are not secrets**, and they are covered at all three scopes
  (`ActionsVariableRepo`, `ActionsVariableOrg`, `EnvironmentVariable`).
- **`VulnerabilityAlerts`.** Evaluated and dropped.
  `GET /repos/{owner}/{repo}/vulnerability-alerts` returns **404 when the feature is off
  and 204 with no body when it is on** — it never returns a body, so no status schema can
  be derived from it and observe has nothing to compare. `AutomatedSecurityFixes` is
  covered precisely because its GET *does* return a body (`enabled`, `paused`).
- **`POST /user/repos` is no longer absent.** User-owned repository creation is modelled by
  the separate `UserRepository` kind — a `RestDefinition` has one create verb and cannot
  choose between two paths, so the user-owned create is its own kind rather than a mode of
  `Repository` (see the `Repository` / `UserRepository` rows above).
- **The git-write kinds are no longer absent.** `RepoContent`, `PullRequest` and `GitRef`
  have all returned natively, after the proxy plugin the three shared was removed and
  publishing moved to `git-provider` (above): `RepoContent` via `status.sha` plus a
  `responseTransform`, now that the `%252F` double-escape is fixed; `PullRequest` via a
  `responseTransform` flattening `head`/`base`; and `GitRef` via a create `requestTransform`
  for the `refs/` prefix plus a `dependentLookups` chain that resolves the base HEAD sha —
  the pre-call dependent read once tracked as oasgen-provider **#120**, shipped in 0.36.0.
  The full designs are in [design-gitref](./design-gitref.md),
  [design-repocontent](./design-repocontent.md)
  and [design-pullrequest](./design-pullrequest.md).

## The `<Kind>Configuration` kinds

For each of the 32 resource kinds, oasgen generates a `<Kind>Configuration` CRD from the
OpenAPI bearer `securityScheme` — `RepositoryConfiguration`, `TeamConfiguration`,
`LabelConfiguration`, and so on. Each carries the token wiring a resource CR references
via `spec.configurationRef.name`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepositoryConfiguration   # one per resource kind — 32 in total
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

The generated name is the kind name plus `Configuration`, so `CodeSecurityConfig` — named
that, not `CodeSecurityConfiguration` — yields `CodeSecurityConfigConfiguration` rather
than a doubled `…ConfigurationConfiguration`.

All 32 may share a single name — the kind is implied by the resource that references it.
That is why `chart/samples/configurations.yaml` ships 31 of the 32 under the same
`github-blueprints-config`, and why **one PAT can drive the whole chart** — except
`UserRepository`, whose repositories are created in the token's own account, so its sample
Configuration (`github-user-config`) carries the intended user's token instead. You only need
the Configuration for the kinds you actually use; the rest are inert. The referenced
`Secret` is provisioned out-of-band ([usage](./usage.md)); the chart ships none of this.

What that PAT needs differs by kind, and the token must satisfy the union of the kinds in
use:

| kinds | what the token needs |
|---|---|
| `Repository` | repository **creation** in the organization — classic `repo` scope, or a fine-grained token with org **Administration: read & write** |
| `Team`, `TeamMembership`, `TeamRepo`, `OrgMembership`, `OrgWebhook`, `OrgRuleset`, `ActionsVariableOrg`, `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` | organization admin rights (classic `admin:org`, or the equivalent fine-grained org permissions) |
| the remaining repository-scoped kinds | repository administration on the target repository |
