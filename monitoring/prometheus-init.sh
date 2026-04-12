#!/bin/sh
set -e
printf '%s' "${PROMETHEUS_METRICS_TOKEN}" > /tmp/prometheus_metrics_token
sed "s|__PROMETHEUS_SCRAPE_TARGET__|${PROMETHEUS_SCRAPE_TARGET:-host.docker.internal:8000}|g" \
    /etc/prometheus/prometheus.yml.template > /tmp/prometheus.yml
exec /bin/prometheus --config.file=/tmp/prometheus.yml --storage.tsdb.retention.time=15d
