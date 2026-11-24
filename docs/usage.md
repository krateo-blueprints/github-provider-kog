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

A Krateo cluster with `oasgen-provider` **≥ 0.76.0, except 0.77.0,** running (it provides
`restdefinitions.ogen.krateo.io` and generates the CRDs + a controller per kind).

0.9.x carried the four kinds the chart started with, but the floor is now **0.76.0**.
0.76.0 is where a create whose outcome is unknown stops at `CreateOutcomeUnknown` instead of being sent again ([#746](https://github.com/krateo-platformops/oasgen-provider/issues/746)); below it, `Issue`, `RepoDeployment` and a draft `Release` can leave duplicates on GitHub ([below](#work-tracking--issues-releases-deployments)). 0.77.0 is excluded: on it a `PullRequest`, `Collaborator` or `UserRepository` whose create outcome is unknown shows `Creating` forever instead of `CreateOutcomeUnknown`, so nothing prompts anyone to act ([#758](https://github.com/krateo-platformops/oasgen-provider/issues/758), fixed in 0.78.0; [below](#a-cr-stuck-after-an-unknown-create)). The chart declares this as `krateo.io/requires-oasgen-provider: ">= 0.76.0, != 0.77.0"` in `Chart.yaml`, from 0.15.0. The Krateo installer's floor gate reads it and refuses to pin this chart beside an oasgen-provider that violates it. A plain `helm install` checks nothing. oasgen-provider has also retracted 0.77.0 itself ([retracted-versions.yaml](https://github.com/krateo-platformops/oasgen-provider/blob/main/retracted-versions.yaml), [#784](https://github.com/krateo-platformops/oasgen-provider/pull/784)), so the installer refuses a 0.77.0 pin whichever chart sits beside it. The previous floor, 0.61.0, is where oasgen-provider refuses to uninstall a generated CRD whose instances it cannot count when a RestDefinition is removed ([#576](https://github.com/krateo-platformops/oasgen-provider/issues/576)); below it, narrowing `kinds` or uninstalling the chart can cascade-delete live CRs ([below](#keeping-a-repository-when-its-cr-is-deleted)).
Before that the floor was 0.52.0, which adds `RestDefinition.spec.serverURL`, which `githubBaseUrl` sets for GitHub Enterprise
(below it the field would be dropped silently and requests would reach api.github.com). Before
that the floor was 0.38.0, where the `GitRef` pattern admission guard reaches the generated CRD. `GitRef`'s
create resolves its base sha with `dependentLookups`, a primitive that landed in 0.36.0.
25 of the 32 kinds also set `compareScope: updatable`, a value
`RestDefinition` CRDs below 0.23.0 reject on apply so their kinds never appear — the
earlier floor, now subsumed by 0.76.0.

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

`PullRequest` needs two repository permissions on a fine-grained token: **Pull requests:
read & write** and **Contents: read**. Without Contents, reading pull requests still
works, so a CR whose pull request already exists observes normally. Only the create fails:
GitHub refuses it with `422` "not all refs are readable", because it must read the head and
base branches. A refusal is permanent, but the controller keeps retrying it on every resync
([krateo-platformops/oasgen-provider#768](https://github.com/krateo-platformops/oasgen-provider/issues/768)),
so a token missing Contents shows up as a steady stream of `422` responses rather than one
failure. Fine-grained permissions can be edited in place, so adding Contents: read fixes
it without changing the Secret. This was seen on 2026-11-17 by another Krateo provider
session (keycloak-provider-kog), running this chart's `PullRequest` kind with a token
scoped to a single repository.

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

**Deleting a `Repository` CR deletes the repository on GitHub**, code and history included
(GitHub's `DELETE /repos/{owner}/{repo}`); so does deleting a `UserRepository` CR. See
[Keeping a repository when its CR is deleted](#keeping-a-repository-when-its-cr-is-deleted).
The full spec/status field list is in [api](./api.md).

### Keeping a repository when its CR is deleted

Annotate the CR:

```yaml
metadata:
  annotations:
    krateo.io/deletion-policy: orphan
```

rest-dynamic-controller then releases the CR's finalizer without calling GitHub, and the
repository stays. It reads the annotation through unstructured-runtime (`pkg/meta`
`ShouldDelete`): `krateo.io/deletion-policy: orphan` keeps the external object, and so does
`krateo.io/management-policy: observe-create-update` or `observe`. One combination defeats it:
`krateo.io/management-policy: observe-delete` deletes the external object **whatever the
deletion policy says**, so never set that management policy on a CR you protect with `orphan`.
The annotation must be on the CR **before** it is deleted. The portal's builder-publish chart sets it on the `Repository` it
renders, so uninstalling a publish never removes the published repository.

A `UserRepository` can **adopt** a repository that already exists in the token's account (its
findby matches by name). Deleting that CR deletes the adopted repository too, although Krateo
never created it, so annotate it if you adopt an existing repository.

Removing the `Repository` RestDefinition (narrowing `kinds`) or uninstalling the chart normally
does not cascade to the CRs, because oasgen-provider refuses to drop a CRD that still has
instances. **Before oasgen-provider 0.61.0 that refusal has a hole**: if the kind cannot be listed
at that moment (its CRD version not served, for example), the instance count reads as zero and
the CRD is uninstalled with its CRs, which are then marked for deletion. Measured on oasgen
0.60.0 (oasgen-provider#576 and #609, fixed in 0.61.0). So do not narrow `kinds` or uninstall
the chart on a cluster with live CRs unless it runs oasgen-provider >= 0.61.0, and keep the
`orphan` annotation on every repository you mean to keep.

#### If the `Repository` CRD is stuck Terminating

If `kubectl get crd repositories.github.krateo.io -o jsonpath='{.status.conditions[?(@.type=="Terminating")].reason}'`
prints `InstanceDeletionInProgress`, every `Repository` CR is already marked for deletion, and the only
thing missing is its controller. The deletion is **pending, not cancelled**: once the controller comes
back (the RestDefinition re-created, or `helm upgrade` restoring the kind), it deletes every repository
whose CR is not annotated. Before you restore anything:

1. annotate every CR you want to keep with `krateo.io/deletion-policy: orphan`. This works on a CR that
   already has a `deletionTimestamp`, because the policy is read when the controller reconciles it;
2. check that none of them sets `krateo.io/management-policy: observe-delete`, which overrides it;
3. only then restore the RestDefinition.

Measured on kind with oasgen-provider 0.60.0, using a local fake API that logged every request it
received. After the controller came back, the unannotated CR received 1 DELETE and the annotated one
received 0. oasgen-provider 0.61.0 and later refuse the CRD uninstall that leads to this state.

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
comparison walks arrays positionally, so a reshuffled `rules`, `bypass_actors` or
`contexts` list reads as a change and is pushed back on the next reconcile. Webhook
`events` is the exception: GitHub keeps it as a set and returns it sorted, so the chart
declares it a set, and its order does not matter on oasgen-provider 0.62.0 or later.

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
  `license_compliance_scanning`). **Every rule type GitHub accepts is modelled**: 25 on
  `RepoRuleset` (including `code_coverage` and `code_quality`), 21 on `OrgRuleset`, where GitHub's
  org API refuses `merge_queue` and `license_compliance_scanning` (live probe, 2026-11-11). The
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
- **`DeploymentBranchPolicy` does not adopt a pattern that already exists.** For a `name`
  the environment already has, GitHub answers the create with `303 See Other` pointing at
  the policy *list*. The CR never gets a `status.id`, so the controller never reads or
  writes that policy: later spec edits are not applied. What the CR reports depends on the
  oasgen-provider version (measured against real GitHub on 0.67.0, 0.69.0, 0.70.0 and 0.71.0):
  - **Below 0.70.0** the controller follows the redirect, reads the list as the created
    policy, and the CR reports `Ready=True` with no `status.id` and no error
    (oasgen-provider#682).
  - **On 0.70.0** the redirect is refused and the CR reports
    `Ready=False/NoIdentifierRecorded`, with a `Warning` event naming the redirect. The
    controller still sends the create again on every resync, about every 3 minutes. GitHub
    refuses each repeat the same way, so no duplicate appears, but the `Warning` repeats and
    `Synced` flips between `ReconcileError` and `ReconcileSuccess` (oasgen-provider#696).
  - **From 0.71.0** the create is sent once. The CR stays `Ready=False/NoIdentifierRecorded`
    and `Synced=False/ReconcileError`. The controller re-checks it a few times after each
    resync and logs *"Cannot observe external resource"* each time, without calling GitHub.
    The state does not clear by itself, because the CR cannot be attached to the existing
    policy. What deleting such a CR does has not been measured. The condition's own message
    warns that the policy on GitHub may then be left unreferenced, so decide which side owns
    the policy before you delete anything.

  Check that `status.id` is set after applying. If it is not, see [Verify](#verify) for the
  query that finds such CRs on every version.
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
- **`Issue`, `RepoDeployment` and a draft `Release` can be created twice.** GitHub assigns their identifier and accepts an identical second create.
  Measured 2026-11-14, sending the same body twice gave two issues, two deployments, and two
  drafts with the same `tag_name`. A published `Release` is refused by `tag_name`, and every
  other POST kind in the chart refused its duplicate. Three routes made the controller send a
  create again, each closed in a different release:
  - **Below 0.68.0:** a create that reached GitHub but then lost the status write after it
    (oasgen-provider#676).
  - **Below 0.70.0, 0.68.0 included:** a lost status write left the CR with no record that a
    create had started, so the next pass created again (oasgen-provider#692). Another
    provider measured duplicates from this on 0.69.0. 0.68.0 and earlier run the same code
    but were not measured separately.
  - **0.69.0 and 0.70.0:** a CR left without an identifier is refused by the controller, and
    that refusal triggers a fresh create on every resync (oasgen-provider#696). Measured on
    `DeploymentBranchPolicy`, where GitHub refuses the repeat. For these three kinds each
    repeat would leave another object (derived from the controller's code, not measured on
    these kinds).

  **Use oasgen-provider 0.71.0 or later**, the first release with all three closed. A CR can
  still be left without an identifier; the query under [Verify](#verify) finds such a CR on
  every version, and it should be compared against GitHub before acting on it.
  **Upgrading does not remove a duplicate an earlier version already created**, and no CR
  mentions it. The CR ends up tracking one of the objects, and the other is left on GitHub.
  If these kinds ran on any version below 0.71.0, compare the issues, deployments and draft
  releases on GitHub against your CRs.

  **A fourth route is open on every oasgen-provider release before 0.76.0.** It is in how
  rest-dynamic-controller and unstructured-runtime, the library it is built on, handle a
  failed create, not in the three fixes above. Sometimes GitHub creates the object but the controller never gets a success
  back (a 5xx, a timeout or a reset connection). The same happens when the success does
  arrive but the controller then fails to process it: the body cannot be read, or the
  identifier cannot be written to status. Either way the controller records the create as
  failed and sends it again. The check that would look for the object first does not run once
  a failure is recorded. The controller retries up to `REST_CONTROLLER_MAX_ERROR_RETRIES`
  times (default 5), so a single CR can send up to six POSTs. For these three kinds, each one
  GitHub accepts leaves another object.
  - **Where this is established:** read in the source of unstructured-runtime v1.18.0, which
    0.71.0 and 0.73.0 ship. The oasgen-provider maintainers read the same rule in every
    runtime version back to v1.9.0 (oasgen-provider 0.60.0).
  - **Measured once, on another provider,** with oasgen-provider 0.73.0 and a test vendor
    that stored the create and then answered 500: six POSTs. **Not measured on a GitHub
    kind.**
  - **When it happens:** only when GitHub commits the create and the controller then does not
    get, or cannot process, the answer, so it is rarer than a plain error.
  - **Nothing on the CR shows it.** If a later attempt gets its answer, the CR tracks that
    object and reports healthy, and the earlier objects stay on GitHub with nothing pointing
    at them. If no attempt does, the CR has no identifier, and [Verify](#verify) finds it.
  - **oasgen-provider 0.75.0 does not close it.** 0.75.0 ships unstructured-runtime
    v1.22.0, which checks whether the object exists before sending a create again. But
    rest-dynamic-controller 0.75.0 reports every create error as "nothing was sent", and
    the runtime takes that as safe to send again, so the check never runs. In source:
    `restResources.go:1790` returns `CreateResult{}`, whose `Requested` is false, and
    `worker.go:1322` then records the create as failed. Measured on kind on 2026-11-16 with
    0.75.0 and an `Issue` whose create GitHub refused with 404, so nothing was created:
    each attempt was recorded as failed in the same second it started and sent again, and
    the CR never reached `CreateOutcomeUnknown`. Another provider measured the lost
    answer itself on 0.75.0 (azuredevops-provider-kog, a create that timed out on the
    controller's side): 2 of 8 trials hit it, and both sent the create again about 2 s
    later with no existence check in between, leaving two objects for one CR. The same
    trial on 0.74.0 left 2, 3 and 2 objects.
  - **oasgen-provider 0.76.0 closes it** (oasgen-provider#747, fixing #746, for both
    triggers above). A create whose outcome is unknown is no longer sent again. The CR stops
    at `Ready=False/CreateOutcomeUnknown` and waits for a person instead. Measured on kind on
    2026-11-16 with 0.76.0 and the same 404 `Issue` trial: each CR sent one POST and reached
    `CreateOutcomeUnknown` within 5 s, and sent nothing more over the next 200 s, with the
    repository by then in place. **Use oasgen-provider 0.76.0 or later for these three
    kinds.** The cost is that a CR in this state needs you; see
    [a CR stuck after an unknown create](#a-cr-stuck-after-an-unknown-create) under Verify.
  - **On releases before 0.76.0, to limit the repeats**, set
    `REST_CONTROLLER_MAX_ERROR_RETRIES` lower in the oasgen-provider chart's `rdc.env`. That
    setting reaches every generated controller, so each of them also gives up sooner on any
    other failing event.

  If these kinds ran on any release before 0.76.0, compare the issues, deployments and draft
  releases on GitHub against your CRs: upgrading does not remove a duplicate already made.
- **`PullRequest` has no delete verb and no close-from-spec.** `state` is PATCH-body-only,
  so it never becomes a spec field. Merge or close the PR on GitHub, then delete the CR.
- **A `PullRequest` without `status.number` looks for an OPEN pull request only.** A new CR,
  or one whose status was lost, finds its pull request by listing the repository's open
  pull requests and matching `head` and `base`. GitHub allows one open pull request per
  pair, so at most one can match. Closed and merged pull requests are not listed.
  - Up to chart 0.14.0 the list included them, so a new CR for a pair that had an older
    closed or merged pull request adopted that old one. It reported Ready with the old
    number, and the pull request it was written for was never opened. A create that never
    reached GitHub was recorded as succeeded. Reusing a branch name (for example
    `builder/<repo>`) was enough to cause it.
  - Measured on kind with oasgen-provider 0.80.0 on 2026-11-17, open-only against the
    old listing, on one repository with branches that already had pull requests:

    | case | listing all pull requests (≤ 0.14.0) | listing open ones (0.15.0) |
    |---|---|---|
    | new CR; the pair has a closed PR | adopted it, opened nothing | opened its own PR |
    | new CR; the pair's only PR is merged | adopted the merged PR | GitHub refused the create (`422 No commits between main and …`) |
    | create never reached GitHub; 2 closed PRs | adopted the newest, recorded the create as succeeded | `CreateOutcomeUnknown`, adopted nothing |
    | own create landed; 1 closed PR besides | adopted its own open PR | adopted its own open PR |

    After adopting a closed pull request, the controller sent `PATCH` requests to it.
    GitHub refused every one (`422`: the base of a closed pull request cannot change), so
    no pull request was edited, but the CR's request did include them.
  - **The cost:** a CR that loses `status.number` after its pull request was merged can
    no longer find it. It tries to open a new one, and GitHub refuses a pull request whose
    head has no commits beyond base. The CR stays at `Ready=False` with `422` in its
    `Synced` message and retries the create: 16 times in the first 4 minutes in the
    measurement, then about once every 3 minutes. Nothing is created. If the branch has
    gained commits since the merge, a new pull request does open, for those commits.
    Delete such a CR, or keep its status (an in-place upgrade does).
- **`Issue` has no delete verb**, because GitHub's REST API cannot delete an issue.
  Deleting the CR only stops Krateo tracking it, and like `PullRequest` it cannot be
  closed from its spec: `state` is update-body-only, so it is not a spec field. Close the
  issue on GitHub, then delete the CR.
- **Some fields are create-only and quietly stay that way**: an `Issue`'s
  `labels`/`assignees`/`milestone` (GitHub returns them as objects rather than the
  strings and numbers it accepts, so comparing them could only produce an update that
  changes nothing) and `assignee`/`type`/`parent_issue_id`, a `Milestone`'s `due_on` (GitHub keeps the day and re-times it to
  midnight in the token account's timezone, so what `GET` returns is not what was
  written — read `status.due_on` to see what it stored), and a `Release`'s
  `generate_release_notes`, `discussion_category_name` and `make_latest` (set once, at create). A `Release`'s `name`, `body`, `draft` and `prerelease` *are*
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
  Every toggle in GitHub's create and update bodies is modelled except `code_security`,
  `secret_protection` and the four `*_options` blocks (reasons in the asset). The chart
  copies none of GitHub's create-time defaults: a toggle left out of the CR gets GitHub's
  default on create and is not compared afterwards.
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

Four RestDefinitions carry `SchemaWarnings` Warning events (and `status.schemaWarnings`) on
every generation, and that is expected. They come from GitHub's own description, not from a
fault in the install:

| RestDefinition | warnings | cause |
|---|---|---|
| `actionsvariableorg`, `actionsvariablerepo`, `environmentvariable` | 1 each | GitHub describes the create's `201` body as a bare `type: object` (an empty object), so the create response has no properties while the `get` response does |
| `repocontent` | 2 | `content` is an object in one response and a string in another |

Any other `SchemaWarnings` event is new and worth reading.

A CR can be `Ready=True` without being managed. If the controller has no identifier for it
(`status.id` or the kind's equivalent) and the kind declares no `findby` lookup, Observe
cannot reach GitHub at all and assumes the resource is up to date
(oasgen-provider#682). Only `Collaborator`, `PullRequest` and `UserRepository` declare
`findby`; the other 29 kinds can land here. Such a CR has no `Observed` condition, and its
`Ready` message starts with a fixed prefix, *"Resource is assumed to be up-to-date"*. A
related variant with the same prefix (*"… Returned body is nil."*) marks a CR whose read
returned `204`/`304`, so its spec was never compared. Either can be found across a cluster:

```console
$ kubectl get $(kubectl api-resources --api-group=github.krateo.io -o name \
      | grep -v configurations | paste -sd, -) -A -o json \
  | jq -r '.items[] | select(any(.status.conditions[]?;
      (.message // "") | startswith("Resource is assumed to be up-to-date")))
      | "\(.kind)/\(.metadata.namespace)/\(.metadata.name)"'
```

An empty result means no CR shows that message. From oasgen-provider 0.69.0 the message no
longer appears. Those releases report `Ready=False/NoIdentifierRecorded` for such a CR
instead and send the create again on every resync, about every 3 minutes. On 0.69.0 each
repeat overwrites the reason with `Creating` within about 2 seconds. On 0.70.0 the reason
stays. From 0.71.0 the create is sent once and the reason stays. The query above misses all
three. This check works on every version measured, 0.67.0 to 0.71.0: it lists CRs that were
created more than 10 minutes ago, whose create was recorded as successful, and which have
never been observed.

```console
$ kubectl get $(kubectl api-resources --api-group=github.krateo.io -o name \
      | grep -v configurations | paste -sd, -) -A -o json \
  | jq -r --argjson min 10 '.items[]
      | select((.metadata.annotations["krateo.io/external-create-succeeded"] // null) != null
          and (any(.status.conditions[]?; .type == "Observed") | not)
          and ((now - (.metadata.creationTimestamp | fromdateiso8601)) > ($min * 60)))
      | "\(.kind)/\(.metadata.namespace)/\(.metadata.name)"'
```

The 10-minute gate leaves out healthy new CRs, which have no `Observed` condition until
their first observe, about 2 minutes in. The age is the CR's own: each repeated create
re-stamps `external-create-succeeded`, so a check on that annotation's age never fires for
a CR stuck in the repeat. The previous version of this check had exactly that flaw.
Measured cause so far: a `DeploymentBranchPolicy` whose pattern already existed (see the
CI/CD caveats above).

### A CR stuck after an unknown create

A CR can also stop before it is ever created, and the check above does not list it, because
no create was ever recorded as successful. The controller found the CR's create still marked
pending (`krateo.io/external-create-pending` is newer than any succeeded or failed marker).
Before creating again it asks whether the object already exists. When it gets no answer, it
refuses rather than risk a second create. The `Ready` condition (`CreateOutcomeUnknown` from
oasgen-provider 0.76.0, `Creating` before it), the `Synced` message and a
`CannotInitializeManagedResource` Warning event all carry a message that starts with
`cannot determine creation result`. The advice in it depends on the version and the kind, and
the reason the check could not answer follows it:

| oasgen-provider | what the message says to do |
|---|---|
| up to 0.82.0 | remove the `krateo.io/external-create-pending` annotation "if it is safe to proceed" |
| 0.83.0 and later | it clears by itself once the check answers; remove the annotation only if it never can, "after verifying whether the external resource exists". From 0.91.1: "only after verifying that the external resource does NOT exist", because removing it sends a create at once |
| 0.86.0 and later, on the 14 kinds listed below | "cannot determine creation result, and never will": verify by hand whether the resource exists "and then remove" the annotation, or delete the CR and keep the resource |

**Do not follow the last one as written.** It does not say what to do when the resource does
exist. Removing the annotation then creates a second one; the two recoveries are below.

On oasgen-provider 0.76.0 or later this is how a create whose outcome is unknown ends: a
5xx, a timeout, a dropped connection, a success the controller could not process, or a
refusal the controller does not read as "nothing was created". Which refusals it reads that
way depends on the version:

| oasgen-provider | a create refused with this is recorded as failed and sent again later | anything else stops here |
|---|---|---|
| 0.76.0 – 0.81.x | `400`, `422` | including `401` and `404` |
| 0.82.0 – 0.83.x | `400`, `401`, `422` (oasgen-provider#793) | including `404` |
| 0.84.0 and later | `400`, `401`, `404`, `422` (oasgen-provider#825) | `409`, 5xx, timeouts |

So before 0.84.0 a create against a repository that does not exist yet stops here even
though GitHub created nothing, and from 0.84.0 it is retried until the repository exists.

Measured on kind on 2026-11-18, released charts, no proxy. Two `Issue` CRs pointed at a
repository that did not exist yet, held for 4 minutes; then the repository was created.

| | 0.83.1 | 0.84.0 |
|---|---|---|
| while the repository is missing | `CreateOutcomeUnknown` within 5 s, 1 `POST` per CR, then none | `Ready=False/Creating`, `external-create-failed` stamped each time; 12 `POST`s per CR in 4 minutes |
| after the repository is created | still stuck after 12 minutes, 0 issues | both `Ready=True` about 1 minute later, exactly 1 issue per title |

On 0.84.0 each series is one `POST` and 5 retries, backing off 1, 2, 4, 8 and 16 s, so it
ends about 30 s after it starts. The next series starts on the controller's next resync,
`REST_CONTROLLER_RESYNC_INTERVAL`: 3 minutes by default, and the controller's startup line
read `resyncInterval` 3m with `maxErrorRetry` 5 and a 1 s minimum retry interval.
The series started 114 s and then 180.0 s apart. The first gap is shorter because the first
series started when the CRs were applied, not on a resync. So a CR whose repository never
appears sends 6 `POST`s every resync, indefinitely. That was measured on 2026-11-21 with 0.84.0: two
`Issue` CRs pointed at a repository that never existed, watched for 21 minutes. Each CR made exactly
6 refused attempts in each of 8 series: the one started when the CRs were applied, and 7 resyncs
180 s apart. Every series started its backoff again at about 1 s, with no taper. The retry limit
of 5 counts per queued event, and each resync queues a new one (oasgen-provider#846). `409` and 5xx stay out on every version: a `409` can mean the object already exists, and
after a 5xx GitHub may have created it and lost the answer. Before 0.76.0 such a create was
sent again instead (see the fourth duplicate-create route under
[Work tracking](#work-tracking--issues-releases-deployments)), and this state was reached
only through a rare race: azuredevops-provider-kog saw it in 1 of 15 forced races on 0.71.0.

To list the CRs in this state:

```console
$ kubectl get $(kubectl api-resources --api-group=github.krateo.io -o name \
      | grep -v configurations | paste -sd, -) -A -o json \
  | jq -r '.items[] | select(any(.status.conditions[]?;
      (.message // "") | startswith("cannot determine creation result")))
      | "\(.kind)/\(.metadata.namespace)/\(.metadata.name)"'
```

What happens next depends on how the kind is read:

- **Read by a `get` keyed on spec fields** (a `Label`, keyed on its name): the kind gets out
  of this state without help. If the object is found, the create is recorded as successful.
  If GitHub answers `404`, the runtime waits 2 minutes, clears the marker and creates.
- **Found through `findby`** (`Collaborator`, `PullRequest`, `UserRepository`; until the
  first observe, their identifiers are not on status, so a `get` cannot address them): if
  the list contains the object, the create is recorded as successful. A list in which
  nothing matches is **not** taken as absence, so these kinds never create again on their
  own. The outcome depends on the oasgen-provider version:
  - **up to 0.76.0, and from 0.78.0:** the CR stops at `CreateOutcomeUnknown`. The message
    starts as above and ends *"existence check: findby listed successfully but no item
    matched the resource's identifiers…"*. The Warning event is
    `CannotInitializeManagedResource`. Recover it as below.
  - **0.77.0 only: the CR shows `Ready=False/Creating`**, and `Synced` says *"a create is
    pending: its outcome could not be determined on this pass and is checked again"*, with a
    `CreateOutcomePending` Warning event instead. It retries forever and asks for no action.
    If the object was never created, nothing will ever match, so the CR never moves on, and a
    parent composition counts it as still converging. This is a defect
    ([krateo-platformops/oasgen-provider#758](https://github.com/krateo-platformops/oasgen-provider/issues/758)),
    fixed in 0.78.0 (#759). Do not run these kinds on 0.77.0. On it, find these CRs with the
    second query below and recover them the same way. An event filter keyed on
    `CreateOutcomePending` finds nothing on any other version.

  Measured on kind on 2026-11-17 with `PullRequest`, on 0.77.0 and on 0.78.0, without
  a proxy. Two CRs were created against a repository that did not exist yet, so the create
  failed with `404` and stayed pending. (From 0.84.0 a `404` create is retried instead, so
  this way of reaching the state no longer works; a lost answer still reaches it.) The repository and both head branches were then
  created, with no pull request, so the list matched nothing. Over a 6-minute hold, 4
  minutes past the 2-minute grace, both versions sent no create and opened no pull
  request. 0.77.0 showed `Creating` throughout. 0.78.0 showed `CreateOutcomeUnknown` within
  12 s. Recovery was the same on both versions:
  - Pull request opened by hand for one CR: the CR found it on the next pass (94 s on both
    versions), recorded it as created and reported `Ready=True`, tracking that pull request.
  - Pending annotation removed on the other CR, after checking there was no pull request:
    the controller sent one create and opened exactly one pull request.

  `Collaborator` was measured the same way on both versions, but only up to the stuck state.
  Its `login` was the token's own account, so no invitation could reach anyone. The `PUT`
  against the missing repository failed with `404` and stayed pending. Once the repository
  existed, the `affiliation=direct` list matched nothing. Over a 6-minute hold neither
  version sent another `PUT`, and GitHub showed no direct collaborator and no invitation.
  0.77.0 showed `Creating`; 0.78.0 showed `CreateOutcomeUnknown` within 15 s. Neither
  recovery step was tried for `Collaborator`. `UserRepository` was not measured: its create
  (`POST /user/repos`) has no repository in the path to make fail, so the stuck state cannot
  be produced without a proxy. It takes the same path in the code.
- **Server-assigned identifier and no `findby`:** until the identifier is on status, the
  question has no answer, so the CR waits indefinitely at `CreateOutcomeUnknown`.
  [configuration](configuration.md) lists those kinds under *Server-assigned identifiers*;
  `Issue`, `RepoDeployment` and a draft `Release` are the ones where a second create would
  be a duplicate.

  From oasgen-provider 0.86.0 each RestDefinition says in advance which group it is in, with
  an `ExistenceAnswerable` condition. On this chart it is `False` on these 14 kinds, measured
  on kind on 0.87.0 through 0.90.0 (2026-11-22) and on 0.91.1 (2026-11-23); `True` on the other 18:

  | kind | GET parameter | mapped from | correct? |
  |---|---|---|---|
  | `Autolink`, `CodeSecurityConfig`, `DeployKey`, `DeploymentBranchPolicy`, `OrgRuleset`, `OrgWebhook`, `Release`, `RepoDeployment`, `RepoRuleset`, `RepoWebhook`, `RunnerGroup` | the kind's `*_id` | `status.id` | yes: GitHub assigns the id |
  | `Issue`, `Milestone` | `issue_number` / `milestone_number` | `status.number` | yes: GitHub assigns the number |
  | `Team` | `team_slug` | `status.slug` | yes: GitHub derives the slug, and it is not a spec field |

  **On 0.86.0 only, `Repository` is wrongly shown as `False` too.** It reads its GET path from
  `status.name` (the name GitHub actually assigned, see [configuration](configuration.md)), but
  before the first create that field is absent and the mapping is skipped, so the path is filled
  from `spec.name` and the existence check can read the repository. The 0.86.0 controller
  behaves that way; only the condition was wrong. 0.87.0 fixed the condition
  (oasgen-provider#880), and the 0.87.0 install shows `Repository` as `True`.

The second query, for 0.77.0 only. A CR with a create in flight shows this message briefly,
so look at the ones that keep it across several resyncs:

```console
$ kubectl get $(kubectl api-resources --api-group=github.krateo.io -o name \
      | grep -v configurations | paste -sd, -) -A -o json \
  | jq -r '.items[] | select(any(.status.conditions[]?;
      (.message // "") | startswith("a create is pending")))
      | "\(.kind)/\(.metadata.namespace)/\(.metadata.name)"'
```

**To recover one, look on GitHub first, then do one of two things.** Both were measured on
kind on 2026-11-16 with oasgen-provider 0.76.0, on two stuck `Issue` CRs, after creating
on GitHub an issue matching each CR:

- **GitHub has the object: write its identifier to the CR's status.** For an `Issue` that
  is the issue number:

  ```console
  $ kubectl patch issues.github.krateo.io <name> -n <namespace> \
      --subresource=status --type=merge -p '{"status":{"number":42}}'
  ```

  Leave the annotations alone. The controller reads the issue on its next pass (76 s in the
  measurement), records the create as successful (`external-create-succeeded` joins
  `external-create-pending`) and reports `Ready=True`, tracking that issue. No create is
  sent. `--subresource=status` is required: without it `kubectl` reports `patched` and the
  apiserver drops the status change.

  **The patch does not start a pass of its own.** The CR keeps showing
  `CreateOutcomeUnknown` until the next periodic one, up to
  `REST_CONTROLLER_RESYNC_INTERVAL` (default 180 s). Wait that long before judging the
  result. Above all, do not fall back to removing the annotation because the CR still looks
  stuck: the object exists at that point, so the controller would create a second one.

  The GitHub measurement reached this state through a `404`, which stands in for a lost
  answer (on 0.84.0 and later a `404` no longer leads here). Another oasgen-generated provider (azuredevops-provider-kog) measured the real
  thing on 0.76.0: its create landed on the vendor, but the controller timed out before the
  answer arrived. The CR stopped at `CreateOutcomeUnknown` with only the pending annotation.
  Writing the identifier the same way, leaving the annotations alone, brought it to
  `Ready=True` on the next resync, about 3 minutes later. The vendor held one object
  throughout. That is one triggered trial in eight.
- **GitHub has no such object: remove the pending annotation.**

  ```console
  $ kubectl annotate issues.github.krateo.io <name> -n <namespace> \
      krateo.io/external-create-pending-
  ```

  The controller sends the create at once. **Do this only after checking GitHub**, because
  it creates whether or not the object exists. In the measurement the issue already existed
  and the CR was re-created anyway: GitHub then held two issues with that title, the CR
  tracked the new one (`#3`), and the first (`#2`) was tracked by nothing. That is the
  advice in the message, followed without checking first.

**Deleting the CR instead depends on the version and the kind.** For the 14 kinds above, from
0.86.0 the CR goes away and **anything the create made on GitHub stays there**, also for a kind
whose CR normally deletes it. The controller records an
`ExternalResourceKeptExistenceUnanswerable` Warning event and calls nothing. To delete the object
too, write its identifier to the CR's status first, wait for `Ready=True`, then delete the CR. Adopting it that way is the
measurement above, on 0.76.0; the delete that follows was not measured.

Measured on kind on 2026-11-24, with no access to GitHub: three CRs carrying the pending
annotation and the controller's finalizer, then deleted. The annotation was set by hand, so no
create had been sent.

| | 0.85.2 | 0.91.1 |
|---|---|---|
| `Issue` (no delete verb) | still there after 5 minutes | gone within 60 s |
| `Milestone` (has a delete verb) | still there after 5 minutes | gone within 60 s, no request sent |
| `Label` (control: read by name, GitHub unreachable) | still there after 5 minutes | still there after 5 minutes |

The `Label` row is intended: its existence can be read once GitHub answers, so deletion waits.
The branch was added in 0.86.0 and has been measured on 0.91.1.

To trace what a kind's controller does against GitHub, set the opt-in
`krateo.io/connector-verbose: "true"` annotation on a single CR and read that kind's own
controller's logs. There is one log to check per kind and no second place to look: with all
32 kinds native, nothing sits in front of them. The annotation works only on the CR being
reconciled: the controller reads it from that object, so setting it on a RestDefinition does
nothing (oasgen-provider#552).

> **Treat verbose as a temporary debug aid only — never leave it on by default, and never set
> it on a CR that carries a secret.** With the annotation on, rest-dynamic-controller dumps
> every request *including the body*, and every response, to the pod log
> (`httputil.DumpRequestOut(req, true)` at
> `go/rest-dynamic-controller/internal/tools/client/restclient.go:1316`, oasgen-provider tag
> 0.56.0). Redaction is narrow by design: it covers only values the provider resolved through a
> `secretRef` (`RedactValues`, :1310-1320, :1407) and nine credential *header* names, among them
> `Authorization`, so the bearer token is not written to the log (`credentialHeaders` and
> `credentialHeaderRe`, :1455-1479). There is deliberately no pattern-based redaction of the
> body (:122). This chart resolves nothing through `secretRef`, so every value a spec sends in
> the request body is written to the log in cleartext. That includes a
> `RepoWebhook`/`OrgWebhook` `spec.config.secret` (the HMAC key, sent on create and update),
> `RepoContent` file content, and anything else in the spec. Pod logs are usually readable far
> more widely than the CR itself (for example through log aggregation), so enable verbose only
> briefly, on a non-sensitive CR, and leave it off entirely on any webhook CR. The samples under
> `chart/samples/` no longer set it.
