// Command github-provider-kog-plugin is a tiny rest-dynamic-controller plugin: a web
// service that normalizes GitHub REST API inconsistencies the pure OpenAPI mapping
// cannot express, so the generated CRs settle to Ready instead of looping create->422.
//
// It is invoked by the rest-dynamic-controller ONLY for the verbs whose RestDefinition
// path points at a plugin route (via a per-operation `servers` override in the OAS →
// this service's ClusterIP DNS); every other verb still goes straight to GitHub.
package main

import (
	"io"
	"log"
	"net/http"
	"os"
	"strings"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", ok)
	mux.HandleFunc("GET /readyz", ok)
	// GitRef observe (get-after-create): see getGitRef.
	mux.HandleFunc("GET /gitref/{owner}/{repo}/{ref...}", getGitRef)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("github-provider-kog-plugin listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}

func ok(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

// getGitRef fixes GitHub's git-ref path asymmetry. Create/update/delete use
// /repos/{owner}/{repo}/git/refs[/{ref}] with the FULL "refs/heads/x", but GET uses
// /repos/{owner}/{repo}/git/ref/{ref} with the ref WITHOUT the "refs/" prefix. The
// rest-dynamic-controller observes (get-after-create) through this route, so a just-
// created ref is actually FOUND — instead of a 404 that makes the controller re-issue
// the create and hit "422 Reference already exists" forever (the CR never goes Ready).
//
// GitHub's get-ref body already exposes {ref, node_id, url, object} at the root, and
// `ref` carries the full "refs/..." that matches the CR identifier, so the response is
// passed through verbatim; only the request PATH is corrected.
func getGitRef(w http.ResponseWriter, r *http.Request) {
	owner := r.PathValue("owner")
	repo := r.PathValue("repo")
	ref := strings.TrimPrefix(r.PathValue("ref"), "refs/") // "refs/heads/x" -> "heads/x"

	upstream := "https://api.github.com/repos/" + owner + "/" + repo + "/git/ref/" + ref
	req, err := http.NewRequest(http.MethodGet, upstream, nil)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	if auth := r.Header.Get("Authorization"); auth != "" {
		req.Header.Set("Authorization", auth)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer func() { _ = resp.Body.Close() }()

	body, _ := io.ReadAll(resp.Body)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(body)
}
