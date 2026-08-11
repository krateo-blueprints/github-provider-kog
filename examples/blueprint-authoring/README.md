---
type: Example
title: blueprint-authoring — the git-write flow end to end
description: The end-to-end blueprint-authoring write-path as three github.krateo.io CRs applied in order — a GitRef creates the builder branch, a RepoContent writes a file onto it, and a PullRequest opens the PR into main — with the one-time token and Configuration wiring they reference.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [example, github, blueprint-authoring, gitref, repocontent, pullrequest]
timestamp: 2026-08-11T00:00:00Z
---

# blueprint-authoring

The exact write-path the Krateo portal Autopilot blueprint builder drives, done by hand:
create a builder branch, write a file onto it, open a pull request into `main` — three
`github.krateo.io` CRs, applied in order. It reuses the CRs shipped under
`chart/samples/`.

## One-time wiring

The three resource CRs each reference a `<Kind>Configuration` via
`spec.configurationRef.name`, which points at a token Secret. Provision both
out-of-band (never via the portal):

```console
$ kubectl create secret generic gh-token -n krateo-system \
    --from-literal=token=<YOUR_GITHUB_PAT>   # scopes: repo (contents/refs/pulls write)

$ kubectl apply -f ../../chart/samples/configurations.yaml
```

`configurations.yaml` creates a `RepoContentConfiguration`, `GitRefConfiguration` and
`PullRequestConfiguration` (all named `github-blueprints-config`, pointing at
`gh-token`).

## The flow

Apply the three CRs in order, waiting for each to reach Ready before the next.

1. **Create the builder branch** — `sha` is omitted, so the provider resolves the
   repo's default-branch HEAD sha automatically:

   ```console
   $ kubectl apply -f ../../chart/samples/test-gitref.yaml
   ```

   (`ref: refs/heads/builder/demo-branch` in repo `krateo/krateo-blueprints`.)

2. **Write a file onto that branch** — `content` is base64-encoded file bytes; omit
   `sha` to create a new file:

   ```console
   $ kubectl apply -f ../../chart/samples/test-repocontent.yaml
   ```

   (writes `charts/demo/Chart.yaml` on `builder/demo-branch`.)

3. **Open the PR** from the builder branch into `main`:

   ```console
   $ kubectl apply -f ../../chart/samples/test-pullrequest.yaml
   ```

## Verify

```console
$ kubectl get gitref,repocontent,pullrequest -n krateo-system
$ # the PR number and URL land in status
$ kubectl get pullrequest test-demo-pr -n krateo-system -o jsonpath='{.status.html_url}{"\n"}'
```

Each sample sets `krateo.io/connector-verbose: "true"`, so
`kubectl logs deploy/<release>-plugin -n krateo-system` shows the observe/create URLs
the controller drives through the plugin. When you are done, delete the CRs to close the
PR and remove the branch.
