# Grafana Dashboard Configuration

This directory contains the pre-configured Grafana dashboards and datasources
for the Nohiki platform. When deploying from scratch, these dashboards will be
automatically provisioned and ready to use on first launch.

## Dashboard Overview

### 1. Nohiki Platform Overview (`nohiki-overview.json`)

**UID:** `nohiki-overview`

The main dashboard showing the full Nohiki platform:

- **System Health Overview**: Real-time status of all services
- **Total Requests/sec**: Aggregate request rate across all services
- **Average Response Time**: Platform-wide response time metrics
- **Error Rate %**: Overall error rate with color-coded thresholds
- **HTTP Request Rate by Service**: Detailed breakdown by service and endpoint
- **Response Time Percentiles**: p50, p95, and p99 latency metrics
- **Log Volume by Service and Level**: Structured log analysis
- **Database Connections**: PostgreSQL connection monitoring
- **Recent Error Logs**: Live error log stream

**Features:**

- Service filtering via template variables
- 30-second auto-refresh
- Color-coded thresholds for quick status assessment
- Integrated with all three observability datasources

### 2. Nohiki Services Detail (`nohiki-services.json`)

**UID:** `nohiki-services`

Focused dashboard for deep-diving into individual service metrics:

- **Service Status**: Health status for selected service
- **Request Rate**: Detailed request patterns by endpoint
- **Response Time Distribution**: Latency percentiles for the service
- **Error Rate by Endpoint**: Error tracking per API endpoint
- **Memory Usage**: Process memory consumption
- **Service Logs**: Filtered log stream for the selected service

**Features:**

- Service selector dropdown for focused analysis
- Endpoint-level granularity
- Memory and performance monitoring
- Integrated log viewing

### 3. Nohiki Database Monitoring (`nohiki-database.json`)

**UID:** `nohiki-database`

Specialized dashboard for PostgreSQL database monitoring:

- **Database Status**: PostgreSQL health indicator
- **Active Connections**: Current connection count with thresholds
- **Database Size**: Storage usage monitoring
- **Transactions/sec**: Transaction rate metrics
- **Connection Count Over Time**: Historical connection patterns
- **Transaction Rate**: Commit vs rollback analysis
- **Query Performance**: Row fetch and return metrics
- **Cache Hit Ratio**: Buffer cache efficiency
- **Slow Queries**: Performance bottleneck identification

**Features:**

- Database-specific metrics and thresholds
- Performance optimization insights
- Connection pool monitoring
- Query performance analysis

## Datasource Configuration

Grafana provisions Prometheus, Loki, Mimir, Tempo, and Pyroscope from `datasources/`.
Tempo (`uid: tempo`) provides traces and links them to Loki logs and Mimir metrics.

The datasource files are the source of truth for internal URLs and correlation settings. If a
provisioned datasource reports a connection error, compare its URL with the corresponding
`nohiki-obs-*` service name in `infra/compose/docker-compose.yml`.

## Automatic Provisioning

### Dashboard Provisioning (`dashboard.yml`)

Configures Grafana to automatically load dashboards from this directory:

- **Provider**: `nohiki-dashboards`
- **Folder**: `Nohiki`
- **Auto-reload**: Every 10 seconds
- **UI Updates**: Allowed
- **Deletion**: Enabled (`disableDeletion: false`); remove the JSON file to delete a provisioned dashboard

### First Launch Behavior

When deploying Nohiki from scratch:

1. **Grafana starts** with the observability profile
2. **Datasources are automatically configured** from the `datasources/` directory
3. **Dashboards are automatically imported** from the `dashboards/` directory
4. **Default dashboard** (Platform Overview) is immediately available
5. **All dashboards appear** in the "Nohiki" folder
6. **No manual configuration required**

## Access Information

- **Grafana URL**: `http://localhost:3001`
- **Default Credentials** (local development only):
  - Username: `admin`
  - Password: `admin`
- **Dashboard Location**: Navigate to "Dashboards" -> "Nohiki" folder

## Customization

### Adding New Dashboards

1. Create a new `.json` file in the `dashboards/` directory
2. Ensure the dashboard has a unique `uid`
3. Use the configured datasource UIDs (`prometheus`, `loki`, `mimir`, `tempo`, `pyroscope`)
4. Grafana will automatically detect and load the new dashboard

### Modifying Existing Dashboards

- Dashboards can be edited through the Grafana UI
- Changes are preserved in the Grafana database
- To make changes permanent, export the dashboard JSON and update the file

### Datasource Updates

- Modify the respective `.yml` files in `datasources/`
- Restart Grafana container to apply changes
- Ensure dashboard queries match any datasource changes

## Troubleshooting

### Dashboards Not Loading

1. Check Grafana logs: `docker logs nohiki-obs-grafana`
2. Verify file permissions on dashboard files
3. Ensure JSON syntax is valid
4. Check provisioning configuration in `dashboard.yml`

### Missing Data

1. Verify datasource connectivity in Grafana UI
2. Check that services are exposing metrics
3. Confirm OTEL collector is running and configured
4. Validate Prometheus scrape targets

### Performance Issues

1. Reduce dashboard refresh rates
2. Limit time ranges for heavy queries
3. Optimize Prometheus query expressions
4. Consider dashboard query caching

## Metrics Reference

### Service Metrics

- `up{job=~"nohiki.*"}`: Service health status
- `http_requests_total`: HTTP request counters
- `http_request_duration_seconds`: Request latency histograms
- `process_resident_memory_bytes`: Memory usage

### Database Metrics

- `pg_up`: PostgreSQL status
- `pg_stat_database_*`: Database statistics
- `pg_settings_max_connections`: Connection limits
- `pg_stat_statements_*`: Query performance (requires pg_stat_statements extension)

### Log Queries (Loki)

- `{service_name=~".+"}`: All service logs
- `{service_name=~".+"} |= "ERROR"`: Error logs only
- `{service_name=~".+"} | json`: Structured log parsing

Dashboards are provisioned automatically on first launch. No manual setup is required.
