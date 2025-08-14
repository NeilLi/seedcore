NS=seedcore-dev

# Option 1: scale to zero first (cleaner)
kubectl -n $NS scale deploy/seedcore-serve-dev --replicas=0 || true

# Delete deployment and service
kubectl -n $NS delete deploy/seedcore-serve-dev --ignore-not-found
kubectl -n $NS delete svc/seedcore-serve-dev --ignore-not-found

# (Last resort, if a stray pod lingers)
kubectl -n $NS delete pod -l app.kubernetes.io/instance=seedcore-serve-dev --force --grace-period=0 || true

