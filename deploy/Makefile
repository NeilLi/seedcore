SHELL := /bin/bash

# ------- Config knobs -------
REGISTRY ?= yourrepo
NAMESPACE ?= seedcore-dev
STAGE ?= dev
APP_NAME ?= seedcore-$(STAGE)-cognitive_core
MIN_READY ?= 1

# Kustomize overlay path
K_OVERLAY := kustomize/overlays/$(STAGE)

# Helm release names
API_REL := seedcore-api-$(STAGE)
SERVE_REL := seedcore-serve-$(STAGE)
RAY_REL := seedcore-ray-$(STAGE)

# ------- Helpers -------
kubens:
	kubectl create ns $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

secret:
	@if [[ -z "$$OPENAI_API_KEY" ]]; then echo "Set OPENAI_API_KEY"; exit 1; fi
	kubectl -n $(NAMESPACE) create secret generic openai --from-literal=api_key=$$OPENAI_API_KEY --dry-run=client -o yaml | kubectl apply -f -

# ------- Kustomize deploy -------
.PHONY: kustomize-apply kustomize-delete
kustomize-apply: kubens secret
	@echo "Applying Kustomize overlay $(K_OVERLAY)"
	kubectl -n $(NAMESPACE) apply -k $(K_OVERLAY)

kustomize-delete:
	kubectl -n $(NAMESPACE) delete -k $(K_OVERLAY) --ignore-not-found

# ------- Helm deploy -------
.PHONY: helm-api helm-serve helm-ray helm-delete
helm-api: kubens secret
	helm upgrade --install $(API_REL) ./helm/seedcore-api -n $(NAMESPACE) \
	  	--set image=$(REGISTRY)/seedcore-api:kind \
	  --set env.SEEDCORE_NS=$(NAMESPACE) \
	  --set env.COG_APP_NAME=$(APP_NAME) \
	  --set env.COG_MIN_READY=$(MIN_READY)

helm-serve: kubens secret
	helm upgrade --install $(SERVE_REL) ./helm/seedcore-serve -n $(NAMESPACE) \
	  --set image=$(REGISTRY)/seedcore-serve:latest \
	  --set env.SEEDCORE_NS=$(NAMESPACE) \
	  --set env.COG_APP_NAME=$(APP_NAME) \
	  --set env.COG_MIN_READY=$(MIN_READY)

helm-ray: kubens
	helm upgrade --install $(RAY_REL) ./helm/raycluster -n $(NAMESPACE)

helm-delete:
	-helm uninstall $(API_REL) -n $(NAMESPACE)
	-helm uninstall $(SERVE_REL) -n $(NAMESPACE)
	-helm uninstall $(RAY_REL) -n $(NAMESPACE)

# ------- Convenience stages -------
.PHONY: dev staging prod
dev:
	$(MAKE) STAGE=dev NAMESPACE=seedcore-dev APP_NAME=seedcore-dev-dev-cognitive_core MIN_READY=1 kustomize-apply

staging:
	$(MAKE) STAGE=staging NAMESPACE=seedcore-staging APP_NAME=seedcore-staging-cognitive_core MIN_READY=1 kustomize-apply

prod:
	$(MAKE) STAGE=prod NAMESPACE=seedcore APP_NAME=seedcore-prod-cognitive_core MIN_READY=2 kustomize-apply

# Helm equivalents:
.PHONY: dev-helm staging-helm prod-helm
dev-helm:
	$(MAKE) STAGE=dev NAMESPACE=seedcore-dev APP_NAME=seedcore-dev-dev-cognitive_core MIN_READY=1 helm-ray helm-serve helm-api

staging-helm:
	$(MAKE) STAGE=staging NAMESPACE=seedcore-staging APP_NAME=seedcore-staging-cognitive_core MIN_READY=1 helm-ray helm-serve helm-api

prod-helm:
	$(MAKE) STAGE=prod NAMESPACE=seedcore APP_NAME=seedcore-prod-cognitive_core MIN_READY=2 helm-ray helm-serve helm-api

# ------- KEDA -------
.PHONY: keda-apply keda-delete
keda-apply:
	kubectl -n $(NAMESPACE) apply -f keda/scaledobject-serve.yaml

keda-delete:
	kubectl -n $(NAMESPACE) delete -f keda/scaledobject-serve.yaml --ignore-not-found





