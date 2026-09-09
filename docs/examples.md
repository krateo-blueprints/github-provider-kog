---
type: ExampleIndex
title: github-provider-kog — examples
description: Index of the runnable examples — the Repository CR that creates the destination repository every repository-scoped sample configures, and the sample CR for each of the 28 kinds under chart/samples/, grouped by area with the order each group must be applied in.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [examples, github, samples]
timestamp: 2026-09-09T00:00:00Z
---

# Examples

- [chart/samples/test-repository.yaml](../chart/samples/test-repository.yaml) — the
  **destination repository**, which comes before every other repository-scoped sample.
  It creates `demo-destination` in the `krateo-blueprints` org with `auto_init: true`,
  so the new repo has a first commit and therefore a default branch — without one a
  `BranchProtection`, a `~DEFAULT_BRANCH` ruleset condition or a `Release` creating its
  tag from `main` has nothing to bind to.
  [usage](./usage.md) works it through field by field.

  ```console
  $ kubectl apply -f chart/samples/configurations.yaml    # incl. RepositoryConfiguration
  $ kubectl apply -f chart/samples/test-repository.yaml
  $ kubectl get repository test-demo-destination -n krateo-system \
      -o jsonpath='{.status.full_name} {.status.default_branch}{"\n"}'
  ```

  Three things to settle before running it. The PAT needs repo-creation rights in the
  org — classic token `repo`, fine-grained token organization **Administration: read &
  write** — which is more than the repository-scoped kinds need, so a token that
  configures an existing repository fine can still fail here. `delete` maps
  to `DELETE /repos/{org}/{name}`, so deleting the CR deletes the repository on GitHub:
  point the sample at a scratch org. And editing the applied CR is pushed to
  GitHub only for fields `PATCH` can send — `Repository` compares with
  `compareScope: updatable`, so `description` or `private` reconcile while the
  create-only `auto_init`, `gitignore_template` and `license_template` do not
  ([usage](./usage.md), [configuration](./configuration.md)).

There is no git-write example any more. `GitRef`, `RepoContent` and `PullRequest` have
been removed along with the proxy plugin that served them, and publishing now runs through
the frontend's `BuilderPublish` claim over `git-provider`
(`AUTOPILOT_PUBLISH_VIA_GIT_PROVIDER` defaults to `"true"`). What each kind did and what
bringing it back natively would take is recorded in [design-gitref](./design-gitref.md),
[design-repocontent](./design-repocontent.md) and
[design-pullrequest](./design-pullrequest.md).

## The sample CRs, by group

The chart ships one sample per kind — `chart/samples/test-<kind>.yaml`, lower-cased —
covering the other 27 kinds as well. Each carries its gotchas in a
header comment and sets `krateo.io/connector-verbose: "true"`, and every one of them
names the `krateo-blueprints` org and a `demo-destination` repository. Edit those first
and work in a **scratch org**: several kinds delete the real thing when their CR is
deleted, and no kind in this chart has ever reconciled against GitHub — the first apply
is the real test.

One `<Kind>Configuration` set serves all of them. `chart/samples/configurations.yaml`
ships one per kind, each named `github-blueprints-config` and pointing at the same
`gh-token` Secret, so applying that one file is the only wiring step any group needs;
the kinds you never use leave their Configuration inert. What the **token** must be
allowed to do does differ by group — the per-group rights table is in
[usage](./usage.md), which also works each group's fields and gotchas through.

```console
$ kubectl apply -f chart/samples/configurations.yaml    # all 28, one shared name
```

### Access

| sample | what it creates |
|---|---|
| `test-team.yaml` | the `platform-engineering` org team |
| `test-teammembership.yaml` | `octocat` as a maintainer of that team |
| `test-teamrepo.yaml` | that team's `push` access to `demo-destination` |
| `test-collaborator.yaml` | `octocat` as a direct `push` collaborator on `demo-destination` |
| `test-orgmembership.yaml` | `octocat` as a plain member of the org |

The team and org kinds need a token with organization admin rights (classic
`admin:org`); `test-collaborator.yaml` is a repository grant and needs only `repo`.
Apply the team before the CRs that reference it — they address it by the **slug** GitHub
derives from its name, which lands on `status.slug`:

```console
$ kubectl apply -f chart/samples/test-team.yaml
$ kubectl get team test-platform-engineering -n krateo-system \
    -o jsonpath='{.status.slug}{"\n"}'
$ kubectl apply -f chart/samples/test-teammembership.yaml
$ kubectl apply -f chart/samples/test-teamrepo.yaml     # + test-repository.yaml first
```

`octocat` is a placeholder. A user who is not yet in the org turns
`test-teammembership.yaml` / `test-orgmembership.yaml` into an invitation — the CR still
reconciles, with `status.state: pending` — while `test-collaborator.yaml` stays not-Ready
until the invitation is accepted.

### Repository configuration

| sample | what it creates |
|---|---|
| `test-reporuleset.yaml` | a ruleset protecting `demo-destination`'s default branch |
| `test-orgruleset.yaml` | the same protection org-wide, carving out `.github` and `sandbox-*` |
| `test-branchprotection.yaml` | classic branch protection on `main` |
| `test-repowebhook.yaml` | a webhook on `demo-destination` |
| `test-orgwebhook.yaml` | one webhook for every repository in the org |
| `test-environment.yaml` | a `production` environment with custom branch policies on |
| `test-deploykey.yaml` | a read-only deploy key for CI |
| `test-autolink.yaml` | `TICKET-1234` → a link to the tracker |

All of the repository-scoped ones want `test-repository.yaml` (or a repository of your
own) first, and `test-branchprotection.yaml` additionally needs the branch to have a
commit. The two org-scoped ones — `test-orgruleset.yaml`, `test-orgwebhook.yaml` —
need `admin:org` instead.

```console
$ kubectl apply -f chart/samples/test-reporuleset.yaml
$ kubectl get reporuleset test-demo-protect-main -n krateo-system \
    -o jsonpath='{.status.id} {.status.enforcement}{"\n"}'
```

Before applying either webhook sample, change `config.secret`: it is the HMAC key GitHub
signs deliveries with and it sits in the CR in clear text.

### CI/CD

| sample | what it creates |
|---|---|
| `test-actionsvariablerepo.yaml` | `KRATEO_REGISTRY` on `demo-destination` |
| `test-actionsvariableorg.yaml` | `KRATEO_REGISTRY` for the whole org |
| `test-environmentvariable.yaml` | `TARGET_CLUSTER` in the `production` environment |
| `test-runnergroup.yaml` | the `krateo-build-runners` self-hosted runner group |
| `test-deploymentbranchpolicy.yaml` | `release/*` as the only branches that may deploy to `production` |
| `test-workflow.yaml` | keeps `release.yaml` enabled |

The three variable samples hold **plaintext**, not secrets — GitHub stores and returns
`value` verbatim — so put nothing in them you would not commit. `test-actionsvariableorg.yaml`
and `test-runnergroup.yaml` are org-scoped (`admin:org`); the rest are repository-scoped.
The environment pair runs after `test-environment.yaml`, which is what supplies the
`custom_branch_policies: true` the branch policy needs:

```console
$ kubectl apply -f chart/samples/test-environment.yaml
$ kubectl apply -f chart/samples/test-environmentvariable.yaml
$ kubectl apply -f chart/samples/test-deploymentbranchpolicy.yaml
```

`test-workflow.yaml` does not create a workflow, and no kind in this chart writes files:
commit `.github/workflows/release.yaml` by some other route first, or point
`workflow_id` at a file that already exists.

### Work tracking

| sample | what it creates |
|---|---|
| `test-label.yaml` | the `krateo/blueprint` label |
| `test-milestone.yaml` | the `v1.0` milestone |
| `test-issue.yaml` | a follow-up issue carrying that label |
| `test-release.yaml` | release `1.0.0`, creating the tag from `main` |
| `test-deployment.yaml` | a deployment record of `main` to `staging` |

The label and the milestone come before the issue that references them — and the issue
references the milestone by the **number** GitHub assigns, not by title:

```console
$ kubectl apply -f chart/samples/test-label.yaml
$ kubectl apply -f chart/samples/test-milestone.yaml
$ kubectl get milestone test-demo-milestone -n krateo-system \
    -o jsonpath='{.status.number}{"\n"}'     # what spec.milestone on an Issue takes
$ kubectl apply -f chart/samples/test-issue.yaml
```

Deleting the `Issue` CR does not delete the issue — GitHub's REST API cannot — it only
stops Krateo tracking it. Close it by setting `state: closed` instead. Deleting the
`Deployment` CR does delete the deployment record; re-deploying means a new CR, since
GitHub has no update endpoint for one.

### Governance

| sample | what it creates |
|---|---|
| `test-customproperty.yaml` | the org-wide `service-tier` property, required on every repository |
| `test-codesecurityconfig.yaml` | the `krateo-baseline` code-security configuration |
| `test-automatedsecurityfixes.yaml` | Dependabot security updates on `demo-destination` |

The first two are org-scoped and need the same admin rights as the access group;
`test-automatedsecurityfixes.yaml` is per repository. Two carry consequences worth
reading before applying: deleting the `CustomProperty` CR removes the definition **and
the values set on every repository in the org**, and `test-codesecurityconfig.yaml`
enables GitHub Advanced Security features — without GHAS licences, set
`advanced_security: disabled` and leave the GHAS-gated toggles at `not_set`, or the
configuration will not round-trip and the controller will `PATCH` it on every reconcile.

```console
$ kubectl apply -f chart/samples/test-automatedsecurityfixes.yaml
$ kubectl get automatedsecurityfixes test-demo-destination-dependabot \
    -n krateo-system -o jsonpath='{.status.enabled} {.status.paused}{"\n"}'
```

That last CR has no settings at all: its existence is the desired state, and deleting it
turns Dependabot security updates back off.
