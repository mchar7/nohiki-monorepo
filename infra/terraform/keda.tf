# KEDA (Kubernetes Event-driven Autoscaling) Installation
resource "helm_release" "keda" {
  count            = var.deployment_type == "aks" ? 1 : 0
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.20.1"
  namespace        = "keda"
  create_namespace = true
  wait             = true
  timeout          = 600

  set = [
    {
      name  = "prometheus.metricServer.enabled"
      value = "true"
    },
    {
      name  = "prometheus.metricServer.port"
      value = "9022"
    },
    {
      name  = "prometheus.operator.enabled"
      value = "true"
    },
    {
      name  = "webhook.replicaCount"
      value = var.app_environment == "prod" ? "2" : "1"
    },
    {
      name  = "operator.replicaCount"
      value = var.app_environment == "prod" ? "2" : "1"
    }
  ]

  depends_on = [azurerm_kubernetes_cluster.aks_cluster[0]]
}

# KEDA Service Monitor for Prometheus integration
resource "kubectl_manifest" "keda_service_monitor" {
  count     = var.deployment_type == "aks" ? 1 : 0
  yaml_body = <<YAML
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: keda-metrics
  namespace: keda
  labels:
    app.kubernetes.io/name: keda
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: keda-operator-metrics-apiserver
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
YAML

  depends_on = [helm_release.keda[0]]
}