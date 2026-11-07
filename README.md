# github-provider-kog

## What is this

A Krateo **KOG** (Krateo OpenAPI Generation) provider, built on
[`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider) **≥ 0.38.0**,
that exposes 32 GitHub REST resources as Kubernetes kinds under the `github.krateo.io`
group. Each kind is listed by its create endpoint; get/update/delete sit on the matching
item path.

**Repositories** — what every other kind hangs off:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Repository` | `POST /orgs/{org}/repos` | create the destination repository itself |
| `UserRepository` | `POST /user/repos` | create the destination repository under the token's own user account rather than an org |
| `GitRef` | `POST /repos/{owner}/{repo}/git/refs` | create a branch or tag ref (`heads/…` or `tags/…`); base sha resolved from the default branch when `sha` is omitted |

**Access** — who can reach what:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Team` | `POST /orgs/{org}/teams` | create an org team (addressed by its server-derived `slug`) |
| `TeamRepo` | `PUT /orgs/{org}/teams/{team_slug}/repos/{owner}/{repo}` | grant a team access to a repo |
| `TeamMembership` | `PUT /orgs/{org}/teams/{team_slug}/memberships/{username}` | put a user in a team as member or maintainer |
| `Collaborator` | `PUT /repos/{owner}/{repo}/collaborators/{login}` | grant a user direct access to one repo |
| `OrgMembership` | `PUT /orgs/{org}/memberships/{username}` | set a user's org membership and role |

**Repository configuration**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `RepoWebhook` | `POST /repos/{owner}/{repo}/hooks` | deliver a repo's events to an endpoint |
| `OrgWebhook` | `POST /orgs/{org}/hooks` | the same, at org scope |
| `DeployKey` | `POST /repos/{owner}/{repo}/keys` | add an SSH deploy key (immutable — no update verb) |
| `Environment` | `PUT /repos/{owner}/{repo}/environments/{environment_name}` | a deployment environment, its reviewers and branch policy |
| `RepoRuleset` | `POST /repos/{owner}/{repo}/rulesets` | branch/tag rules for one repo |
| `OrgRuleset` | `POST /orgs/{org}/rulesets` | the same ruleset document, org-wide |
| `Autolink` | `POST /repos/{owner}/{repo}/autolinks` | map a ticket prefix to an external URL (immutable) |
| `BranchProtection` | `PUT /repos/{owner}/{repo}/branches/{branch}/protection` | the protection document of one branch |

**CI/CD**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `ActionsVariableRepo` | `POST /repos/{owner}/{repo}/actions/variables` | a plaintext Actions variable on a repo |
| `ActionsVariableOrg` | `POST /orgs/{org}/actions/variables` | the same, at org scope |
| `EnvironmentVariable` | `POST /repos/{owner}/{repo}/environments/{environment_name}/variables` | the same, scoped to an environment |
| `RunnerGroup` | `POST /orgs/{org}/actions/runner-groups` | an org self-hosted runner group |
| `DeploymentBranchPolicy` | `POST /repos/{owner}/{repo}/environments/{environment_name}/deployment-branch-policies` | which branches/tags may deploy to an environment |
| `Workflow` | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` | enable (create) / disable (delete) an existing workflow file |

**Work tracking**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `Label` | `POST /repos/{owner}/{repo}/labels` | an issue/PR label |
| `Milestone` | `POST /repos/{owner}/{repo}/milestones` | a milestone (`due_on` is create-only — see below) |
| `Issue` | `POST /repos/{owner}/{repo}/issues` | open and update an issue (no delete — REST has none) |
| `PullRequest` | `POST /repos/{owner}/{repo}/pulls` | open and update a pull request (no delete, and no close from spec) |
| `Release` | `POST /repos/{owner}/{repo}/releases` | a release |
| `RepoDeployment` | `POST /repos/{owner}/{repo}/deployments` | an immutable deployment record |

**Governance**:

| Kind | GitHub API | Purpose |
|------|-----------|---------|
| `CustomProperty` | `PUT /orgs/{org}/properties/schema/{property_name}` | define an org custom property |
| `CodeSecurityConfig` | `POST /orgs/{org}/code-security/configurations` | an org code-security configuration |
| `AutomatedSecurityFixes` | `PUT /repos/{owner}/{repo}/automated-security-fixes` | the Dependabot security-updates toggle for one repo |

The per-kind verbs, identifiers and `compareScope` are in
[docs/configuration.md](docs/configuration.md); the reasoning behind each choice is in the
`chart/templates/rd-<kind>.yaml` comments.

**Not covered, deliberately.** GitHub Actions, Dependabot and Codespaces *secrets* are not
expressible here: writing one takes an `encrypted_value` (a LibSodium sealed box) plus the
`key_id` of a repository public key fetched beforehand, and a `RestDefinition` can do
neither client-side crypto nor a dependent lookup. Variables are **not** secrets — GitHub
stores and returns `value` verbatim — and are covered at repo, org and environment scope.
`VulnerabilityAlerts` was evaluated and dropped: `GET
/repos/{owner}/{repo}/vulnerability-alerts` answers 404 when the feature is off and 204
with **no body** when it is on, so it never returns anything a status schema could be
derived from. `AutomatedSecurityFixes` is covered for exactly the opposite reason — its
GET does return a body (`enabled`, `paused`).

**The git-write kinds, all now returned.** `GitRef`, `RepoContent` and
`PullRequest` were the transport of the **legacy blueprint-publish path**, where the
Autopilot builder wrote a chart tree to a repo (`GitRef` → `RepoContent` per file →
`PullRequest`) as `github.krateo.io` CRs. The frontend now defaults to an SCM-agnostic
route instead: `AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"` in the frontend
chart's `values.yaml` **and** `values.schema.json`, so a fresh install publishes through a
`BuilderPublish` claim over `git-provider`, and the `github.krateo.io` route is the
explicit `"false"` fallback. The three were also the only kinds that needed the companion
proxy plugin, so it went when they left `github.krateo.io`.

All three have since returned **natively**, without the plugin: `PullRequest` (a
`responseTransform` flattening `head`/`base`), `GitRef` (a `requestTransform` for the
`refs/` prefix plus a `dependentLookups` chain that resolves the base sha, needing
oasgen-provider **≥ 0.38.0**) and `RepoContent` (`status.sha` plus a `responseTransform`,
now that the `%252F` double-escape is fixed in 0.23.0). What each did, and what its native
restoration took, is recorded per
kind: [docs/design-gitref.md](docs/design-gitref.md),
[docs/design-repocontent.md](docs/design-repocontent.md),
[docs/design-pullrequest.md](docs/design-pullrequest.md).

`Repository` is what creates a destination repo in the first place — until it existed, a
blueprint could only be published into a repository someone had already made by hand. Its
OAS defaults `auto_init` to `true` deliberately: a repository created with `auto_init:
false` has no commit and therefore no default branch, so nothing can branch from it or
commit against it until someone pushes by hand.

The chart ships 32 `RestDefinition`s + the trimmed OpenAPI spec each references (as a
`ConfigMap`), and nothing else — **no runtime component of its own**: no Deployment, no
Service, no image, no proxy. `oasgen-provider` watches the RestDefinitions, generates the
CRDs under `github.krateo.io`, and auto-deploys a `rest-dynamic-controller` per kind. All
32 kinds are **native**: every one of their verbs goes straight to GitHub. See
[docs/overview.md](docs/overview.md).

## Install

Prerequisite: a Krateo cluster with `oasgen-provider` **≥ 0.38.0** — it provides
`restdefinitions.ogen.krateo.io`, and 0.38.0 is where the `GitRef` pattern admission guard
reaches the CRD. `GitRef`'s base-sha `dependentLookups` landed in 0.36.0; 0.23.0 is where
`compareScope: updatable` arrives, which 25 of the 32 kinds declare — a floor now subsumed
by 0.38.0.

Per the Krateo "everything is a Composition" rule, this chart is installed as a
**component** — a `component-pins` entry that the core-provider CDC turns into a
`CompositionDefinition` — not via `helm install`. See [docs/usage.md](docs/usage.md).

For local development against a kind cluster only:

```console
$ helm upgrade --install github-provider-kog ./chart --namespace krateo-system
```

## Configure

The chart surface is two values: `kinds`, which picks the kinds to render (default all 32, each one a controller pod), and `resourceGroup` (default `github.krateo.io`) — the API
group the generated CRDs land under. Everything else is fixed mapping in `chart/assets/`
and `chart/templates/`.

Authentication is provisioned **out-of-band**. Each RestDefinition's OpenAPI declares a
bearer `securityScheme`, so oasgen generates a per-kind `<Kind>Configuration` CRD and
adds `spec.configurationRef` to every resource CR. Create a token Secret and one
Configuration per kind pointing at it:

```console
$ kubectl create secret generic gh-token -n krateo-system \
    --from-literal=token=<YOUR_GITHUB_PAT>
$ kubectl apply -f chart/samples/configurations.yaml   # all 32 <Kind>Configuration CRs
```

One PAT can drive the whole chart: all 32 Configurations may share a single name
(`github-blueprints-config`), since the kind is implied by the resource that references
it. What the PAT must be *allowed* to do differs by kind, though — `Repository` needs
repository creation in the org (classic `repo`; fine-grained org **Administration: read &
write**), and the org-scoped kinds such as `Team` and `OrgMembership` need org admin
rights. You only need the
Configurations for the kinds you actually use; the rest are inert. (`CodeSecurityConfig`
is named that rather than `CodeSecurityConfiguration` so its generated auth kind is
`CodeSecurityConfigConfiguration`, not a doubled `…ConfigurationConfiguration`.)

Whatever drives these kinds only **references** these Configuration CRs; it never creates
them or the Secret. For builder publishing, the second chart in this repo,
`github-provider-kog-config`, renders the two Configurations it needs; the Secret stays
yours to create. Full surface: [docs/configuration.md](docs/configuration.md).

## Examples

- [examples/blueprint-authoring](examples/blueprint-authoring/README.md) — the one-time
  token + `<Kind>Configuration` wiring, and `github.krateo.io` CRs applied in order
  against a scratch repo.
- `chart/samples/` — the 32 `<Kind>Configuration` CRs and one applyable test CR per kind
  (`test-<kind>.yaml`).

## Docs

The full documentation bundle follows the Krateo Documentation Standard (OKF):

- [docs/index.md](docs/index.md) — the map of the bundle.
- [docs/overview.md](docs/overview.md) — how it works: RestDefinitions → CRDs +
  controllers.
- [docs/usage.md](docs/usage.md) — install, provision auth, drive the kinds, verify.
- [docs/configuration.md](docs/configuration.md) — values, mappings, invariants.
- [docs/api.md](docs/api.md) — the generated CRDs and the CompositionDefinition.
- [docs/examples.md](docs/examples.md) — the runnable examples.
- [docs/release.md](docs/release.md) — how a release ships.
- [docs/log.md](docs/log.md) — curated history.
- [docs/llms.txt](docs/llms.txt) — the file-by-file index.

Each git-write kind that left with the plugin keeps a design document — what the kind did,
what the plugin did for it, and the native `RestDefinition` that replaces it (`RepoContent`,
`PullRequest` and `GitRef` all restored):
[docs/design-gitref.md](docs/design-gitref.md),
[docs/design-repocontent.md](docs/design-repocontent.md),
[docs/design-pullrequest.md](docs/design-pullrequest.md).

## Develop & release

- **Charts** — `chart/` is the provider and `config-chart/` the publishing Configurations;
  each `values.schema.json` types its values (and is what the CDC derives the component CRD
  from).
- **Release** — one plain-semver tag (`X.Y.Z`, no `v`) drives `release-oci.yaml`, which
  packages both charts to `oci://ghcr.io/krateo-blueprints/charts` at the same version, then
  publishes the same bytes to the helm index at `https://krateo-blueprints.github.io/charts/operators`.
  There is no image in this repo any more. Details: [docs/release.md](docs/release.md).
- **CI** — `lint.yaml` runs the shared `lint-docs` docs-standard check; `security.yml`
  runs the shared org security workflow.
