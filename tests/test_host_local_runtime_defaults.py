from __future__ import annotations

import importlib
import os
import sys

import pytest


def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_ray_utils_prefers_localhost_without_cluster_env(monkeypatch):
    for key in ("SERVE_GATEWAY", "RAY_ADDRESS", "POD_NAMESPACE", "SEEDCORE_NS"):
        monkeypatch.delenv(key, raising=False)

    ray_utils = _reload("seedcore.utils.ray_utils")
    assert ray_utils.SERVE_GATEWAY == "http://127.0.0.1:8000"


def test_database_defaults_prefer_local_hosts_outside_k8s(monkeypatch):
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "PG_DSN",
        "NEO4J_HOST",
        "NEO4J_URI",
        "NEO4J_BOLT_URL",
        "POD_NAMESPACE",
        "SEEDCORE_NS",
    ):
        monkeypatch.delenv(key, raising=False)

    database = _reload("seedcore.database")
    assert database.POSTGRES_HOST == "127.0.0.1"
    assert database.NEO4J_HOST == "127.0.0.1"
    assert "@127.0.0.1:5432/" in database.PG_DSN


def test_memory_runtime_defaults_prefer_local_backends_outside_k8s(monkeypatch):
    for key in (
        "PG_DSN",
        "POSTGRES_HOST",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "NEO4J_URI",
        "NEO4J_BOLT_URL",
        "NEO4J_HOST",
    ):
        monkeypatch.delenv(key, raising=False)

    runtime = _reload("seedcore.memory.runtime")
    assert runtime._host_local_default_pg_dsn().startswith("postgresql://")
    assert "@127.0.0.1:5432/" in runtime._host_local_default_pg_dsn()
    assert runtime._host_local_default_neo4j_uri() == "bolt://127.0.0.1:7687"
