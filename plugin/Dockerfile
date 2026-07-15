# github-provider-kog rest-dynamic-controller plugin — stdlib-only Go service.
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /plugin .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /plugin /plugin
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/plugin"]
