---
type: Usage
title: krateo-github-provider-kog — usage
description: How to run the provider — install it as a Krateo component, provision the GitHub token Secret and one Configuration CR per kind, author a chart tree with GitRef then RepoContent then PullRequest, and verify the generated CRDs and controllers.
resource: oci://ghcr.io/krateo-blueprints/charts/krateo-github-provider-kog
tags: [krateo, install, oasgen-provider, github, blueprint-authoring]
timestamp: 2026-08-11T00:00:00Z
---

# Usage

## Prerequisite

A Krateo cluster with `oasgen-provider` **≥ 0.9.x** running (it provides
`restdefinitions.ogen.krateo.io` and generates the CRDs + a controller per kind).

## Install — as a Krateo component

Per the Krateo "everything is a Composition" rule, this chart is installed as a
**component** — a `component-pins` entry that becomes a `CompositionDefinition`
reconciled by the core-provider CDC — not via `helm install`. The core-provider
generates this chart's CompositionDefinition CRD from `values.schema.json`
([api](./api.md)); pin the chart in the Installer and the CDC does the rest:

```yaml
# Installer CR — component-pins entry (illustrative)
- chart: krateo-github-provider-kog
  version: <released version>
  repository: oci://ghcr.io/krateo-blueprints/charts
```

For local development against a kind cluster only:

```console
$ helm upgrade --install krateo-github-provider-kog ./chart --namespace krateo-system
```

## Provision the token and the Configuration CRs

Each RestDefinition's OpenAPI declares a bearer `securityScheme`, so oasgen-provider
generates a per-kind `<Kind>Configuration` CRD and adds `spec.configurationRef` to
every resource CR. Provision, **out-of-band**, a token Secret plus one Configuration
CR per kind pointing at it. First the Secret:

```console
$ kubectl create secret generic gh-token \
    --namespace krateo-system \
    --from-literal=token=<YOUR_GITHUB_PAT>   # PAT scopes: repo (contents/refs/pulls write)
```

Then one Configuration per kind (all three may share a name — the kind is implied by
the resource that references it); see `chart/samples/configurations.yaml`:

```yaml
apiVersion: github.krateo.io/v1alpha1
kind: RepoContentConfiguration   # + GitRefConfiguration + PullRequestConfiguration
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

The Krateo portal write-path **references** these Configuration CRs
(`spec.configurationRef.name`); it never creates them or the Secret. The PAT is
created and stored by an operator, never handled by the browser or snowplow.

## Author a chart tree — the blueprint write-path

The three kinds compose the git flow the Autopilot blueprint builder uses: create a
branch, write each file, open a PR. Apply them in order
([examples](./examples.md), `chart/samples/`):

1. **`GitRef`** — create the builder branch. Leave `sha` out and the provider resolves
   the repo's default-branch HEAD sha automatically, so an author never needs a commit
   sha:

   ```yaml
   apiVersion: github.krateo.io/v1alpha1
   kind: GitRef
   metadata:
     name: test-builder-branch
     namespace: krateo-system
   spec:
     configurationRef:
       name: github-blueprints-config
     owner: krateo
     repo: krateo-blueprints
     ref: refs/heads/builder/demo-branch
   ```

2. **`RepoContent`** — write each file on that branch. `content` is base64-encoded file
   bytes; omit `sha` to create, or let the provider update in place if the file exists.

3. **`PullRequest`** — open the PR from the builder branch into `main`.

## Verify

```console
$ # oasgen should generate the CRDs + a controller per kind
$ kubectl get crd | grep github.krateo.io
$ kubectl get deploy -n krateo-system | grep -E 'repocontent|gitref|pullrequest|plugin'
```

Set `krateo.io/connector-verbose: "true"` on a resource CR (as the samples do) and
watch `kubectl logs deploy/<release>-plugin` to see the observe/create URLs the
controller drives through the plugin.
