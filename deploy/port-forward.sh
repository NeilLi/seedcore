#!/bin/bash

# mgmt/dashboard/Client/metrics
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 8265:8265 &
kubectl -n seedcore-dev port-forward svc/seedcore-svc-head-svc 10001:10001 &

# serve HTTP
kubectl -n seedcore-dev port-forward svc/seedcore-svc-serve-svc 8000:8000 &

wait