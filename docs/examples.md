---
type: ExampleIndex
title: github-provider-kog — examples
description: Index of the runnable examples under examples/ — the end-to-end blueprint-authoring flow (GitRef then RepoContent then PullRequest) against a scratch repo, plus the Repository CR that creates the destination repo that flow writes into.
resource: oci://ghcr.io/krateo-blueprints/charts/github-provider-kog
tags: [examples, github, blueprint-authoring]
timestamp: 2026-08-11T00:00:00Z
---

# Examples

- [examples/blueprint-authoring](../examples/blueprint-authoring/README.md) — the
  end-to-end write-path the Autopilot blueprint builder drives, as three
  `github.krateo.io` CRs applied in order: a `GitRef` creates the builder branch, a
  `RepoContent` writes a file onto it, and a `PullRequest` opens the PR into `main`. It
  reuses the `chart/samples/` CRs and shows the one-time token + `<Kind>Configuration`
  wiring they reference.
- [chart/samples/test-repository.yaml](../chart/samples/test-repository.yaml) — the
  **destination repository**, which comes before that write-path: `Repository` →
  `GitRef` → `RepoContent` (per file) → `PullRequest`. It creates `demo-destination`
  in the `krateo-blueprints` org with `auto_init: true`, so the new repo has a first
  commit and therefore a default branch — without one the `GitRef` has no base sha to
  branch from and the `RepoContent` has nothing to commit against.
  [usage](./usage.md) works it through field by field.

  ```console
  $ kubectl apply -f chart/samples/configurations.yaml    # incl. RepositoryConfiguration
  $ kubectl apply -f chart/samples/test-repository.yaml
  $ kubectl get repository test-demo-destination -n krateo-system \
      -o jsonpath='{.status.full_name} {.status.default_branch}{"\n"}'
  ```

  Three things to settle before running it. The PAT needs repo-creation rights in the
  org — classic token `repo`, fine-grained token organization **Administration: read &
  write** — which is more than the contents/refs/pulls scopes the other three kinds
  need, so a token that drives the write-path fine can still fail here. `delete` maps
  to `DELETE /repos/{org}/{name}`, so deleting the CR deletes the repository on GitHub:
  point the sample at a scratch org. And editing the applied CR is pushed to
  GitHub only for fields `PATCH` can send — `Repository` compares with
  `compareScope: updatable`, so `description` or `private` reconcile while the
  create-only `auto_init`, `gitignore_template` and `license_template` do not
  ([usage](./usage.md), [configuration](./configuration.md)).
