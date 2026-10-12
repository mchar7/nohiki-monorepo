# kgateway for Nohiki

kgateway is the Gateway API implementation for Nohiki, providing ingress routing via the standard Kubernetes Gateway API.

## Why kgateway?

Nohiki uses kgateway to configure ingress through Kubernetes Gateway API resources and TrafficPolicy CRDs.
The [Gateway API benchmarks](https://github.com/howardjohn/gateway-api-bench) informed the choice.
Benchmark results depend on the tested versions, topology, and workload; they are not deployment guarantees.

## Installation

Gateway components are **not installed imperatively**. Flux owns the vendored
Gateway API experimental CRDs `v1.3.0` at
`infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml`, whose payload is
checksum-verified as
`sha256:3e7a27e4456ff3d68606a6a8516306aaff354d6f0950b32bb31930669b7bf8b8`.
The foundation chart at `infra/k8s/helm-foundation` pins kgateway CRDs and
controller `v2.3.6` plus agentgateway CRDs and controller `v1.3.1` as locked
Helm dependencies. The v1.3.0 experimental bundle serves the v1alpha2 TCP,
TLS, and UDP Route APIs that agentgateway v1.3.1 discovers.

Flux reconciles the Gateway API CRDs before the foundation infrastructure stack,
then reconciles the platform stack. This single ownership chain applies every
CRD before the controllers and routes that consume it.

To bring the whole stack up locally:

```bash
just k8s-reconcile-local   # build + push images, then Flux reconciles the stacks
# or, on a cluster with images already pushed:
just gitops-full
```

## Helm Integration

The Nohiki Helm chart automatically creates Gateway API resources when `global.ingress.enabled: true`.

### Configuration

```yaml
global:
  ingress:
    enabled: true
    gatewayClass: kgateway
    host: nohiki.localhost
    s3:
      enabled: true
      host: s3.nohiki.localhost
      service: nohiki-rustfs
      port: 9000
    tls:
      enabled: false
      secretName: ""
    trafficPolicy:
      rateLimit:
        average: 100
        burst: 50
        period: "60s"
```

The local workstation reaches these Gateway hosts at
`http://nohiki.localhost:8080` and `http://s3.nohiki.localhost:8080`.

### Created Resources

| Resource | Name | Purpose |
| ---------- | ------ | --------- |
| Gateway | `nohiki-gateway` | Entry point for traffic |
| HTTPRoute | `nohiki-jwks-route` | `/.well-known/jwks.json` -> user-auth-service |
| HTTPRoute | `nohiki-auth-route` | `/api/v1/auth/*` -> user-auth-service |
| HTTPRoute | `nohiki-account-route` | `/api/v1/account/*` -> user-auth-service |
| HTTPRoute | `nohiki-ping-route` | `/api/ping` -> bff-service |
| HTTPRoute | `nohiki-api-route` | `/api/*` -> bff-service |
| HTTPRoute | `nohiki-sse-route` | `/api/v1/documents/events` -> bff-service with unlimited request timeout |
| HTTPRoute | `nohiki-otel-traces-route` | Optional OTLP/HTTP trace ingest route |
| HTTPRoute | `nohiki-s3-route` | Local-only exact-host route from `s3.nohiki.localhost` to the in-cluster RustFS S3 port, without path rewriting |
| HTTPRoute | `nohiki-frontend-route` | `/*` -> frontend when the frontend chart is enabled |
| TrafficPolicy | `nohiki-rate-limit` | Rate limiting for API routes |
| TrafficPolicy | `nohiki-security-headers` | Security response headers |

## Troubleshooting

### Check Gateway Status

```bash
kubectl get gateway -n nohiki
kubectl describe gateway nohiki-gateway -n nohiki
```

### Check HTTPRoute Status

```bash
kubectl get httproute -n nohiki
kubectl describe httproute nohiki-api-route -n nohiki
```

### Check kgateway Controller

```bash
kubectl get pods -n kgateway-system
kubectl logs -n kgateway-system -l app=kgateway
```

### Verify GatewayClass

```bash
kubectl get gatewayclass
```

## References

- [kgateway Documentation](https://kgateway.dev/docs/)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
- [Gateway API Benchmarks](https://github.com/howardjohn/gateway-api-bench)
