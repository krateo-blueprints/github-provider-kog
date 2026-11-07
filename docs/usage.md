---
type: Usage
title: github-provider-kog — usage
description: How to run the provider — install it as a Krateo component, provision the GitHub token Secret and one Configuration CR per kind (all 32 may share a single name), create the destination repository with Repository, drive the other 31 kinds group by group (access, repository configuration, CI/CD, work tracking, governance), and verify the generated CRDs and controllers. The chart ships no runtime component of its own.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [krateo, install, oasgen-provider, github]
timestamp: 2026-09-09T00:00:00Z
---

# Usage

## Prerequisite

A Krateo cluster with `oasgen-provider` **≥ 0.38.0** running (it provides
`restdefinitions.ogen.krateo.io` and generates the CRDs + a controller per kind).

0.9.x carried the four kinds the chart started with, but the floor is now **0.38.0**:
0.38.0 is where the `GitRef` pattern admission guard reaches the generated CRD. `GitRef`'s
create resolves its base sha with `dependentLookups`, a primitive that landed in 0.36.0.
25 of the 32 kinds also set `compareScope: updatable`, a value
`RestDefinition` CRDs below 0.23.0 reject on apply so their kinds never appear — the
earlier floor, now subsumed by 0.38.0.

Nothing else is required. The chart renders 32 ConfigMaps and 32 RestDefinitions and
nothing more: there is no Deployment, no Service and no image of its own to pull. Every
verb of every kind is a native call to `api.github.com`, made by the
rest-dynamic-controller oasgen-provider generates.

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
    --from-literal=token=<YOUR_GITHUB_PAT>   # PAT scopes: repo (one repository's settings)
                                             # + repo creation in the org (Repository)
                                             # + admin:org for the org-scoped kinds
```

`Repository` needs **more** than the repository-scoped kinds: creating a repository in an
organization is an admin operation, not a write against a repository that already exists.
A classic token needs `repo`; a fine-grained token needs the organization permission
**Administration: read & write** on top of the repository permissions the rest use. A
token scoped for one repository's settings drives those kinds and fails on `Repository`
alone.

The 32 kinds spread the same way: a single PAT can drive the whole chart, but the rights
it needs grow with the groups you actually use.

| kinds | what the token must be allowed to do | classic scope |
|---|---|---|
| `Issue`, `PullRequest`, `Label`, `Milestone`, `Release`, `RepoDeployment`, `RepoContent` | write issues, labels, releases, deployments and file contents on one repository | `repo` |
| `RepoWebhook`, `DeployKey`, `Environment`, `DeploymentBranchPolicy`, `RepoRuleset`, `BranchProtection`, `Autolink`, `Collaborator`, `AutomatedSecurityFixes`, `ActionsVariableRepo`, `EnvironmentVariable`, `Workflow` | administer one repository's settings | `repo` |
| `Repository` | create and delete repositories in the organization | `repo`, and the org must permit the token to create repositories |
| `UserRepository` | create and configure repositories under the token's own user account | `repo` |
| `Team`, `TeamMembership`, `TeamRepo`, `OrgMembership`, `OrgWebhook`, `OrgRuleset`, `ActionsVariableOrg`, `RunnerGroup`, `CustomProperty`, `CodeSecurityConfig` | administer the organization | `admin:org`, on top of `repo` |

Fine-grained tokens do not map onto that column: they grant one permission per area —
repository **Administration**, **Webhooks**, **Environments**, **Variables**, and
organization **Members**, **Administration**, **Custom properties**, **Self-hosted
runners** — and GitHub's reference page for the endpoint a kind calls is the authority
on which one. The endpoint per kind is in [configuration](./configuration.md). Expect a
token that drives the repository-scoped kinds perfectly to `403` on the org-scoped ones
until it is widened.

Then one Configuration per kind. They may all share a name — the kind is implied by the
resource that references it — which is why `chart/samples/configurations.yaml` ships 31
of the 32 under the same `github-blueprints-config` — all but `UserRepository`, whose
repositories are created in the token's own account, so it gets its own Configuration
carrying the intended user's token:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepositoryConfiguration    # one of 32: TeamConfiguration, RepoRulesetConfiguration,
                                 # LabelConfiguration, EnvironmentConfiguration,
                                 # CustomPropertyConfiguration, …
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

Two things about that set:

- **You only need the Configurations for the kinds you use.** The rest are inert — a
  `<Kind>Configuration` with no resource CR referencing it costs nothing. Applying the
  whole file is simply the least fiddly way to start.
- **`CodeSecurityConfig`'s is `CodeSecurityConfigConfiguration`.** The kind is named
  `CodeSecurityConfig`, not `CodeSecurityConfiguration`, precisely so the generated auth
  kind reads that way instead of a doubled `…ConfigurationConfiguration`.

Whatever drives these kinds **references** these Configuration CRs
(`spec.configurationRef.name`); nothing in the portal creates them or the Secret. The PAT
is created and stored by an operator, never handled by the browser or snowplow.

## Create the destination repository

`Repository` creates the repo every other repository-scoped kind then configures, so it
comes **first**. Like all 32 kinds it is fully native: create (`POST /orgs/{org}/repos`)
and get/update (`GET`/`PATCH /repos/{org}/{name}`) go straight to
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

Five things to know before you apply it:

- **Leave `auto_init: true`** (it is the OAS default). A repository created with
  `auto_init: false` has no commit and therefore no default branch, so everything that
  addresses a branch — `BranchProtection`, a `~DEFAULT_BRANCH` ruleset condition, a
  `Release` creating its tag from `main` — has nothing to bind to until someone commits
  by hand.
- **The path params are `org` and `name`, not GitHub's `owner`/`repo`.** Deliberate:
  the same two CR fields serve the create path (`/orgs/{org}/repos`), the create body
  (`name`) and the get/update/delete path (`/repos/{org}/{name}`), so the CRD carries
  one pair of fields instead of an `org`/`owner` duplicate to keep in sync. The
  repository-scoped kinds that configure it keep GitHub's own `owner`/`repo` spelling —
  that pair is this `org`/`name` pair, named the way GitHub names it.
- **Editing an applied `Repository` reaches GitHub, but only for fields `PATCH` can
  send.** The RestDefinition sets `compareScope: updatable` rather than the default
  `fullSpec`, so Observe compares exactly the spec fields the update body can express:
  `description`, `homepage`, `has_issues`, `has_wiki` and `has_projects` are compared and
  pushed. `default_branch` and `archived` are update-body-only, so they are not spec fields
  and cannot be set from the CR at all. `auto_init`, `gitignore_template` and
  `license_template` are not reconciled under *any* scope, because GitHub never echoes
  them on `GET` and the comparison skips a spec key the response does not carry. Set them
  at create time; changing them afterwards does nothing.
- **`private` and `visibility` are honoured at create and ignored thereafter, on
  purpose.** They are kept out of the `PATCH` body, so flipping a repository's exposure in
  GitHub is *not* reverted by the next reconcile, and editing them on the applied CR does
  nothing. Change exposure in GitHub. This is deliberate rather than an omission: consumers
  render a `Repository` on every composition and core-provider's default `UpgradePolicy` is
  `Automatic`, so while these were compared, a consumer changing its rendered value did not
  only affect repositories created afterwards — it PATCHed the ones that already existed,
  and a private→public flip is not undone by flipping back (forks, clones, caches and
  search indexing survive it). That makes `updatable` **load-bearing** on this kind rather
  than defensive: GitHub echoes both fields on every `GET`, so `fullSpec` — which is also
  what you get by deleting the line — would compare them straight back in
  ([configuration](./configuration.md)).
- **Org-scoped and user-scoped creates are separate kinds.** This `Repository` kind maps
  the org-scoped create (`POST /orgs/{org}/repos`); GitHub's other create endpoint,
  `POST /user/repos` for user-owned repos, is its own kind, `UserRepository` — a
  RestDefinition has one create verb and cannot choose between two paths at runtime. Krateo
  destinations are normally org-owned; use `UserRepository` when the destination belongs to
  the token's own account.

`Repository` has **no delete verb**, so deleting the CR orphans the repository
on GitHub. The full spec/status field list is in [api](./api.md).

The status fields carry what the kinds that follow need: `full_name`, `clone_url`,
`ssh_url`, `html_url` and the `default_branch` a ruleset or a branch protection binds to.

```console
$ kubectl get repository test-demo-destination -n krateo-system \
    -o jsonpath='{.status.full_name} {.status.default_branch}{"\n"}'
```

## Publishing a chart tree — not this chart's job

Three kinds used to sit here: `GitRef`, `RepoContent` and `PullRequest`, composing a
create-a-branch → write-each-file → open-a-PR flow for the Autopilot blueprint builder.
The companion proxy plugin — whose only callers they were — went when they left the
publish chain.

Publishing is the frontend's job now, over an SCM-agnostic route:
`AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"` in the frontend chart's
`values.yaml` **and** its `values.schema.json`, so a fresh install publishes through a
`BuilderPublish` claim over `git-provider`; the `github.krateo.io` route is the explicit
`"false"` fallback. Configure publishing there, not here.

What each kind did, and exactly what bringing it back natively took, is written down, one
document per kind: [GitRef](./design-gitref.md), [RepoContent](./design-repocontent.md),
[PullRequest](./design-pullrequest.md). **All three have since returned** — natively,
without the plugin. `PullRequest` needs one `responseTransform` on the get verb that
flattens GitHub's head/base objects back to the branch strings the spec carries, with
`compareScope: updatable` to drop the create-only fields the PATCH can never fix.
`GitRef` needs a `requestTransform` for the `refs/` prefix plus a `dependentLookups` chain
that resolves the base HEAD sha for a sha-less create — the pre-call dependent read once
tracked as oasgen-provider **#120**, which landed in **0.36.0**. `RepoContent` relocates
`spec.branch` onto GitHub's `?ref` via a `fieldMapping`, canonicalizes the base64 `content`
and lifts `sha`/`html_url` to the root with `responseTransform`s, and drops a stale `sha`
on create with `requestTransform: del(.sha)` — the `status.sha` the update and delete
bodies need is auto-populated, so no pre-call read is required.

What is left in the chart is 32 native kinds and no runtime component at all.

## The other 31 kinds

`Repository` creates the destination; the other 31 kinds cover the rest of a repository's
and an organization's configuration. They share a shape — reference a
`<Kind>Configuration`, name the target with GitHub's own path parameters (`owner`/`repo`,
or `org`), set the fields, apply — and every verb of every one of them is native
([overview](./overview.md)).

Each has a sample at `chart/samples/test-<kind>.yaml`, lower-cased
(`test-teammembership.yaml`, `test-reporuleset.yaml`, …), whose header comment carries
that kind's gotchas. They all name the `krateo-blueprints` org and a `demo-destination`
repository, and they are validated against the deployed RestDefinition CRD rather than
run end to end against GitHub — no kind in this chart has ever reconciled against GitHub,
so the first apply of a kind is the real test. Point them at a scratch org.

One rule cuts across every group: **array order is part of the desired state.** Drift
comparison walks arrays positionally, so a reshuffled `events`, `rules`, `bypass_actors`
or `contexts` list reads as a change and is pushed back on the next reconcile.

### Access — who can reach what

| kind | what it manages | apply after |
|---|---|---|
| `Team` | an org team; GitHub derives its slug from `name` | — |
| `TeamMembership` | a user's role on a team (`member` / `maintainer`) | `Team` |
| `TeamRepo` | a team's permission on a repository | `Team` + `Repository` |
| `Collaborator` | one user's direct permission on one repository | `Repository` |
| `OrgMembership` | a user's membership of the organization | — |

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: Team
metadata:
  name: test-platform-engineering
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  org: krateo-blueprints
  name: platform-engineering
  description: "Platform engineering team, managed by Krateo"
  privacy: closed                              # `secret` (the default) is owners + members
  notification_setting: notifications_enabled
```

```console
$ kubectl get team test-platform-engineering -n krateo-system \
    -o jsonpath='{.status.slug}{"\n"}'
```

- **There is no `team_slug` field on `Team`, on purpose.** GitHub derives the slug from
  `name` (`Platform Engineering` → `platform-engineering`) and every item verb addresses
  the team by it, so it is server-assigned and lands on `status.slug`. `TeamMembership`
  and `TeamRepo` take that **slug**, not the display name: name teams in already
  slug-shaped form, or read `status.slug` before writing the CRs that reference them.
- **Membership can be pending, and only some of it is observable.** A `TeamMembership`
  or `OrgMembership` for a user who is not yet in the org creates an invitation: the CR
  reconciles anyway and `status.state` reads `pending` until they accept. `Collaborator`
  is the exception — GitHub turns a non-member into a repository invitation that observe
  cannot see, so that CR stays not-Ready until acceptance.
- **Ask `Collaborator` for a permission at or above what the user already holds** through
  the org or a team. `status.role_name` reports the role GitHub computes, which can be
  higher; when it is, the CR never settles and the controller re-issues the PUT every
  reconcile.
- **`TeamRepo` carries both `org` and `owner`** — the first scopes the team, the second
  the repository. They usually hold the same value and are still two fields, because a
  team can be granted access to a fork owned outside the organization.

### Repository configuration — settings and protection

| kind | what it manages | apply after |
|---|---|---|
| `RepoRuleset` | a ruleset on one repository | `Repository` |
| `OrgRuleset` | a ruleset across the organization | — |
| `BranchProtection` | classic branch protection on one branch | `Repository`, with the branch committed |
| `RepoWebhook` | a webhook on one repository | `Repository` |
| `OrgWebhook` | one webhook for every repository in the org | — |
| `Environment` | a deployment environment and its branch-policy gate | `Repository` |
| `DeployKey` | a public SSH key granting git access to one repository | `Repository` |
| `Autolink` | a ticket-reference → URL rule | `Repository` |

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepoRuleset
metadata:
  name: test-demo-protect-main
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  owner: krateo-blueprints
  repo: demo-destination
  name: protect-default-branch
  target: branch
  enforcement: active
  bypass_actors:
    - actor_type: OrganizationAdmin     # takes no actor_id
      bypass_mode: always
  conditions:
    ref_name:
      include: ["~DEFAULT_BRANCH"]      # concrete ref — required because merge_queue is present
                                        # (a wildcard such as ~ALL would 422; ~DEFAULT_BRANCH is fine)
  rules:
    - type: non_fast_forward            # no parameters — a bare `- type:` entry
    - type: deletion
    - type: pull_request                # …but this one's parameters are all-or-nothing
      parameters:
        required_approving_review_count: 1
        dismiss_stale_reviews_on_push: true
        require_code_owner_review: false
        require_last_push_approval: false
        required_review_thread_resolution: true
    - type: merge_queue                 # all seven keys required; needs a concrete ref (see conditions)
      parameters:
        merge_method: SQUASH            # MERGE | SQUASH | REBASE
        grouping_strategy: ALLGREEN     # ALLGREEN | HEADGREEN
        check_response_timeout_minutes: 60
        min_entries_to_merge: 1
        min_entries_to_merge_wait_minutes: 5
        max_entries_to_merge: 5
        max_entries_to_build: 5
    - type: commit_message_pattern      # one of the five *_pattern rules
      parameters:
        operator: starts_with           # starts_with | ends_with | contains | regex
        pattern: "JIRA-"
        name: require-ticket-prefix     # optional human label; not the ruleset's name
        negate: false                   # optional
```

- **`parameters` is a union keyed by `type`.** Set only the keys belonging to that rule
  type — and, when the type has required keys, *all* of them: flattening the union drops
  GitHub's per-type `required` list, so the CRD cannot enforce it and a partial
  `pull_request` object is a `422`, not a silent ignore. Rules with no parameters are
  written as a bare `- type:` entry (e.g. `creation`, `non_fast_forward`,
  `license_compliance_scanning`). **All 23 of GitHub's rule types are modelled.** The
  branch-protection set, `merge_queue` and the five pattern rules were round-trip-verified
  live on 2026-11-03, and `code_scanning`, `copilot_code_review` and the four push rules on
  2026-11-04 — all on a **Team-plan** org, order preserved and casing verbatim (the pattern
  rules are **not** Enterprise-gated). Two types are modelled from GitHub's REST schema but
  were **rejected with a `422` on a Team-plan org's repository rulesets** and so could not
  round-trip there (see below): `workflows` and `license_compliance_scanning`.
- **`merge_queue` needs a concrete ref.** A ruleset carrying a `merge_queue` rule must set
  `conditions.ref_name` to a non-wildcard ref — `refs/heads/<branch>` or `~DEFAULT_BRANCH`,
  not `~ALL` — or GitHub rejects it with `422 Wildcard ref names are not supported when
  merge queue is enabled`. `tag_name_pattern` likewise belongs on a `target: tag` ruleset
  (GitHub rejects a tag rule in a branch-target ruleset).
- **The four push rules need `target: push`.** `file_path_restriction`,
  `max_file_path_length`, `file_extension_restriction` and `max_file_size` are only valid on
  a ruleset whose `target` is `push`; GitHub `422`s them on a branch- or tag-target ruleset.
  `file_path_restriction` and `max_file_size` also take an optional `ignored_file_paths`;
  when you omit it, GitHub echoes it back as `[]` on GET — harmless, because the drift
  comparison walks only the keys the CR declares, so an unset `ignored_file_paths` is not
  compared.
- **`workflows` and `code_scanning` take hand-supplied identifiers** — a workflow by
  `repository_id` + `path`, a code-scanning tool by name (e.g. `CodeQL`).
- **`workflows` and `license_compliance_scanning` were `422`-rejected on a Team-plan org.**
  Both are modelled (they are in GitHub's REST schema and a `422` is a loud, visible failure —
  the CR goes `Synced=False` with GitHub's message, not a silent drop), but on repository
  rulesets in a Team-plan org `workflows` returned `422 Invalid rule 'workflows': Invalid
  parameter workflows: Workflow error at index 0:` (even with a real workflow file and valid
  `repository_id`/`path`/`ref`/`sha`) and `license_compliance_scanning` returned `422 Invalid
  rule 'license_compliance_scanning':`. Not verified on Enterprise or at the org level.
- **Neither ruleset kind has a `ruleset_id` field.** GitHub assigns it on create; the
  provider carries it in `status.id` and binds get/update/delete from there. `OrgRuleset`
  additionally needs `conditions.repository_name` to say which repositories it covers —
  only the `repository_name` style is modelled (`~ALL` plus fnmatch patterns), not
  targeting by repository id or by org custom property.
- **`BranchProtection` is the pre-ruleset mechanism, and omitted controls mean OFF.** The
  create/update sends the explicit nulls GitHub requires for `required_status_checks`,
  `enforce_admins`, `required_pull_request_reviews` and `restrictions`, so a control left
  out is switched off rather than left alone. The branch
  must already have a commit — a protection `PUT` against an empty branch is a `404` —
  and `restrictions` is org-only. Write `contexts` and `restrictions` sorted; the
  observed lists come back that way.
- **Webhook secrets sit in the CR in clear text, and the CR owns them.** `config.secret`
  is the HMAC key GitHub signs deliveries with and there is no Secret-backed field for it,
  so treat `RepoWebhook` / `OrgWebhook` CRs as sensitive — or leave it out and verify
  deliveries another way. The CR is **authoritative**: a secret set out-of-band (UI,
  Terraform) is cleared on the next config update, because the whole `config` map is re-sent
  and GitHub replaces it wholesale. Set it in `spec.config.secret` and do not rotate it
  elsewhere.
- **These kinds own their object/array fields wholesale.** For `RepoRuleset`, `OrgRuleset`,
  `BranchProtection`, `RepoWebhook` and `OrgWebhook`, an update re-sends the *whole* value of
  each managed object/array, so anything added out-of-band that the CR cannot express (a
  ruleset rule of an unmodelled type, a UI-set branch-protection sub-control) is deleted on the
  next reconcile. Do not mix CR-managed and hand-managed state on the same ruleset / protection
  / webhook — see
  [configuration → Updates send whole values](./configuration.md#updates-send-whole-values--what-a-cr-owns).
  (`Environment` is different: its protection-rule PUT is a **merge**, so a key the CR omits is
  left untouched — see its entry below.)
- **`DeployKey` and `Autolink` are immutable.** GitHub has no update endpoint for either;
  to rotate a key or change an autolink prefix, delete the CR and create a new one.
- **`Environment`'s two `deployment_branch_policy` booleans must disagree** —
  GitHub `422`s if both are true or both false — and `custom_branch_policies: true` is
  what makes a `DeploymentBranchPolicy` possible at all. `reviewers` takes numeric user
  and team ids, not logins. GitHub returns `reviewers`, `wait_timer` and
  `prevent_self_review` only nested under the `anyOf`-typed `protection_rules` array, so the
  get verb carries a responseTransform that flattens them back to the top-level PUT shape:
  they are **observed and reconciled**, and a reviewer removed in the UI is restored. Write
  `reviewers` sorted by `(type, id)` (the transform sorts them and the comparison is
  positional). **Omission keeps, explicit clears** (verified live): the protection-rule PUT is
  a merge, so a CR that omits `reviewers` / `wait_timer` / `prevent_self_review` leaves the
  out-of-band value alone and does not reconcile it; set a field to take ownership, and send
  `reviewers: []` / `wait_timer: 0` to actively clear. **Set `prevent_self_review: true` only
  together with a non-empty `reviewers` list** — GitHub carries it inside the required-reviewers
  rule, so with no reviewers it stores nothing and a CR that set it true re-applies forever
  (never converges); admission cannot reject that until
  [oasgen-provider#396](https://github.com/krateo-platformops/oasgen-provider/issues/396). The
  `User` reviewer path is verified live; the `Team` path is modelled identically but was not
  live-tested (the test org had no teams).

### CI/CD — variables, runners, deployment gates

| kind | what it manages | apply after |
|---|---|---|
| `ActionsVariableRepo` | a plaintext Actions variable on one repository | `Repository` |
| `ActionsVariableOrg` | an org-wide plaintext Actions variable | — |
| `EnvironmentVariable` | a plaintext variable scoped to one environment | `Environment` |
| `RunnerGroup` | an organization self-hosted runner group | — |
| `DeploymentBranchPolicy` | which branches or tags may deploy to an environment | `Environment` with `custom_branch_policies: true` |
| `Workflow` | the enabled state of a committed workflow file | the file committed in the repository |

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: ActionsVariableRepo
metadata:
  name: test-demo-registry-var
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  owner: krateo-blueprints
  repo: demo-destination
  name: KRATEO_REGISTRY
  value: ghcr.io/krateo-blueprints
```

- **Variables are not secrets.** GitHub stores and returns `value` verbatim — which is
  exactly why these kinds are expressible at all — so nothing on this path is encrypted.
  Never put a token or password in one. Actions, Dependabot and Codespaces *secrets* are
  absent from the chart on purpose: they need a LibSodium sealed box computed
  client-side, which a RestDefinition cannot do ([overview](./overview.md)).
- **For the variable kinds `name` is identity, not a label.** It is the create-body field
  and the `{name}` path segment at once, so editing it does not rename the variable — it
  points the CR at a different one, which the controller then creates. Delete and
  recreate to rename. `RunnerGroup` is keyed by the id GitHub assigns instead, so *its*
  `name` is renamable in place.
- **Membership lists are create-only.** `ActionsVariableOrg`'s `selected_repository_ids`
  and `RunnerGroup`'s `selected_repository_ids` / `runners` are never echoed on read, so
  they are not compared and editing them later does nothing. Adjust them through the
  sub-resources `status.selected_repositories_url` and `status.runners_url` point at.
- **The environment-scoped kinds do not create the environment.** `EnvironmentVariable`
  `404`s against an environment that does not exist, and `DeploymentBranchPolicy` `404`s
  — not a validation error — against one without `custom_branch_policies: true`. Apply
  `Environment` first.
- **`Workflow` does not create a workflow.** No kind in this chart writes files, so
  `.github/workflows/…` has to be committed by whatever else pushes into the repository;
  name it in `workflow_id` once it is there. What the CR owns is the enabled state:
  create switches it on, deleting the CR switches it off, and a workflow somebody
  disables in the UI is switched back on at the next reconcile.

### Work tracking — issues, releases, deployments

| kind | what it manages | apply after |
|---|---|---|
| `Label` | a repository label | `Repository` |
| `Milestone` | a milestone; its number lands on `status.number` | `Repository` |
| `Issue` | an issue; its number lands on `status.number` | `Repository` (+ `Label` / `Milestone` if referenced) |
| `PullRequest` | a pull request; its number lands on `status.number` | `Repository` (+ the head branch must exist and differ from base) |
| `Release` | a release, creating its tag if absent | `Repository` |
| `RepoDeployment` | an immutable deployment record | `Repository` (+ `Environment` if the target is gated) |

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: Issue
metadata:
  name: test-demo-issue
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  owner: krateo-blueprints
  repo: demo-destination
  title: "Review the generated blueprint chart"
  body: "Authored by Krateo. Check values.schema.json before the first release tag."
  labels:
    - krateo/blueprint       # create-only, like assignees and milestone
  # milestone: 1             # a Milestone CR's status.number, not its title
```

- **Numbers are server-assigned.** `Issue` and `Milestone` get theirs from GitHub on
  create, and get/update/delete address the resource through `status.number` — there is
  no `issue_number` or `milestone_number` field to set.
- **`PullRequest` has no delete verb and no close-from-spec.** `state` is PATCH-body-only,
  so it never becomes a spec field. Merge or close the PR on GitHub, then delete the CR.
- **`Issue` has no delete verb**, because GitHub's REST API cannot delete an issue.
  Deleting the CR only stops Krateo tracking it, and like `PullRequest` it cannot be
  closed from its spec: `state` is update-body-only, so it is not a spec field. Close the
  issue on GitHub, then delete the CR.
- **Some fields are create-only and quietly stay that way**: an `Issue`'s
  `labels`/`assignees`/`milestone` (GitHub returns them as objects rather than the
  strings and numbers it accepts, so comparing them could only produce an update that
  changes nothing), a `Milestone`'s `due_on` (GitHub keeps the day and re-times it to
  midnight in the token account's timezone, so what `GET` returns is not what was
  written — read `status.due_on` to see what it stored), and a `Release`'s
  `generate_release_notes`. A `Release`'s `name`, `body`, `draft` and `prerelease` *are*
  compared and pushed.
- **`Label`'s `name` is its identity, and `color` is lower-case hex without the `#`.**
  `"D73A4A"` reads as permanent drift because GitHub echoes it lower-cased, and editing
  `name` is not a rename — GitHub renames through a second `new_name` body field the CR
  cannot carry, so it creates a *second* label and orphans the first.
- **`RepoDeployment` is an immutable record.** GitHub has no update endpoint for one, which
  is why the kind uses `compareScope: identifiersAndStatus`: editing the spec changes
  nothing, and deploying again means applying a new CR. Keep `auto_merge: false` (the
  CRD default, deliberately against GitHub's own `true`) — left true, a ref behind the
  default branch is merged instead of deployed and GitHub answers `202` with no
  deployment, so no id, so nothing observable.

### Governance — org-wide policy

| kind | what it manages | apply after |
|---|---|---|
| `CustomProperty` | an org custom-property definition | — |
| `CodeSecurityConfig` | an org code-security baseline | — |
| `AutomatedSecurityFixes` | Dependabot security updates on a repository | `Repository` |

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: CustomProperty
metadata:
  name: test-demo-tier
  namespace: krateo-system
spec:
  configurationRef:
    name: github-blueprints-config
  org: krateo-blueprints
  property_name: service-tier
  value_type: single_select
  description: "Operational tier of the service this repository holds"
  allowed_values: [tier-1, tier-2, tier-3]
  default_value: tier-3
  required: true
  values_editable_by: org_actors
```

- **`CustomProperty`'s `PUT` is an upsert**, so create and update are the same call:
  editing `allowed_values`, `required` or `default_value` reconciles straight back onto
  the definition. Deleting the CR removes the definition **and the values set on every
  repository in the org**.
- **`CodeSecurityConfig` defines a baseline, nothing more.** Attaching it to repositories
  and making it the org default are separate GitHub actions on an existing configuration
  rather than fields of it, and are not modelled. Keep the toggles consistent with
  `advanced_security`: secret scanning, push protection and code-scanning default setup
  are GHAS features, and enabling them alongside `advanced_security: enabled` — the shape
  of GitHub's own "GitHub recommended" configuration — is the combination observed to
  round-trip unchanged. A value GitHub does not store exactly as sent is permanent drift
  and a `PATCH` on every reconcile. Without GHAS licences, set
  `advanced_security: disabled` and leave the GHAS-gated toggles at `not_set`;
  `not_set` means "leave the repository's own setting alone".
- **`AutomatedSecurityFixes` has no settings — its existence is the desired state.**
  Deleting the CR turns Dependabot security updates back off, and turning them off in the
  UI is reverted at the next reconcile. `status.paused` reports Dependabot's own back-off
  on a repository whose security PRs nobody merges: reported, never fought.
- **There is no `VulnerabilityAlerts` kind**, deliberately. Its `GET` returns `404` when
  the feature is off and `204` with no body when it is on, so no response exists for a
  status schema to be derived from. `AutomatedSecurityFixes` is covered precisely because
  its `GET` does return a body (`enabled`, `paused`) ([overview](./overview.md)).

## Verify

```console
$ # oasgen should generate a CRD per kind, plus a <Kind>Configuration CRD for each
$ kubectl get crd | grep -c github.krateo.io     # 64 = 32 kinds + 32 Configurations
$ kubectl get restdefinitions.ogen.krateo.io -n krateo-system
$ # and a rest-dynamic-controller Deployment per kind it has reconciled
$ kubectl get deploy -n krateo-system \
    | grep -E 'repository|team|ruleset|environment|label'
```

Every Deployment that shows up there was generated by oasgen-provider, because the chart
ships none of its own: the release renders 32 ConfigMaps and 32 RestDefinitions and
nothing else.

To trace what a kind's controller does against GitHub, set the opt-in
`krateo.io/connector-verbose: "true"` annotation on a single CR and read that kind's own
controller's logs. There is one log to check per kind and no second place to look: with all
32 kinds native, nothing sits in front of them.

> **Treat verbose as a temporary debug aid only — never leave it on by default, and never set
> it on a CR that carries a secret.** With the annotation on, rest-dynamic-controller dumps
> every request *including the body*, and every response, to the pod log
> (`httputil.DumpRequestOut(req, true)` at
> `go/rest-dynamic-controller/internal/tools/client/restclient.go:1185`, oasgen-provider tag
> 0.50.0). Redaction is narrow by design: it covers only values the provider resolved through a
> `secretRef` (`RedactValues`, :1179-1189, :1276) and credential *header* names
> (`credentialHeaderRe`, :1289-1348) — there is deliberately no pattern-based redaction of the
> body (:114). This chart resolves nothing through `secretRef`, so every value a spec sends in
> the request body is written to the log in cleartext. That includes a
> `RepoWebhook`/`OrgWebhook` `spec.config.secret` (the HMAC key, sent on create and update),
> `RepoContent` file content, and anything else in the spec. Pod logs are usually readable far
> more widely than the CR itself (for example through log aggregation), so enable verbose only
> briefly, on a non-sensitive CR, and leave it off entirely on any webhook CR. The samples under
> `chart/samples/` no longer set it.
