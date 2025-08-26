kubectl delete job seedcore-bootstrap-dispatchers -n seedcore-dev
kubectl apply -f k8s/bootstrap-dispatchers-job.yaml -n seedcore-dev
