"""Opt-in localhost routes for one configured synthetic admission endpoint."""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import HTTPException, Request, Response

from seedcore.models.action_intent import PolicyCase
from .build_admission import ReviewedSimulationBuild
from .component_registry import parse_json
from .cw_simulation import CwSimulationService
from .cw_token_authority import CwTokenAuthority
from .fast_spine.store import ClaimStore


def _private_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('service configuration/key must be a private regular file (0600)')
    data = path.read_bytes()
    if not 0 < len(data) <= maximum:
        raise ValueError('service configuration/key size exceeded')
    return data


def load_cw_simulation_service(config_path: Path) -> CwSimulationService:
    """Explicit operator configuration only. Never generate keys/roles/approval here."""
    config = parse_json(_private_file(config_path, 65536))
    config_path = config_path.resolve(strict=True)
    fields = {'schemaVersion', 'sourcePath', 'sourceSha256', 'executorDigest', 'review', 'policyCase', 'signingKeyPath', 'keyRef', 'claimStorePath'}
    studio_evidence = config.get('schemaVersion') == 'seedcore.cw-g02.service-config.v2'
    signed_evidence = config.get('schemaVersion') in {'seedcore.cw-g02.service-config.v1', 'seedcore.cw-g02.service-config.v2'}
    if signed_evidence:
        fields |= {'receiptSigningKeyPath', 'receiptKeyRef'}
    if studio_evidence:
        fields |= {'evidenceTrustPath', 'evidenceTrustSha256'}
    if set(config) != fields or config['schemaVersion'] not in {'seedcore.cw-g01.service-config.v1', 'seedcore.cw-g02.service-config.v1', 'seedcore.cw-g02.service-config.v2'}:
        raise ValueError('unsupported service configuration')
    def local(name):
        p = Path(config[name])
        return p if p.is_absolute() else config_path.parent/p
    source = local('sourcePath')
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 262144:
        raise ValueError('bounded pinned endpoint source required')
    key = load_pem_private_key(_private_file(local('signingKeyPath'), 4096), password=None)
    receipt_signer = None
    if signed_evidence:
        from .cw_evidence import CwReceiptSigner
        receipt_signer = CwReceiptSigner(load_pem_private_key(
            _private_file(local('receiptSigningKeyPath'), 4096), password=None), config['receiptKeyRef'])
    evidence_verifier = None
    if studio_evidence:
        from .cw_evidence_studio import CwStudioVerifier
        from .cw_evidence import read_json_file
        trust_path = local('evidenceTrustPath')
        if trust_path.is_symlink() or not trust_path.is_file() or trust_path.stat().st_mode & 0o022:
            raise ValueError('operator trust snapshot must be a regular file without group/other write access')
        evidence_verifier = CwStudioVerifier(read_json_file(trust_path, 32768), trust_sha256=config['evidenceTrustSha256'])
    review = ReviewedSimulationBuild.model_validate_json(json.dumps(config['review']))
    store = ClaimStore(local('claimStorePath'))
    try:
        service = CwSimulationService(source.read_bytes(), source_sha256=config['sourceSha256'], review=review,
            policy_case=PolicyCase.model_validate(config['policyCase']), authority=CwTokenAuthority(key, config['keyRef']), store=store,
            executor_digest=config['executorDigest'], receipt_signer=receipt_signer, evidence_verifier=evidence_verifier)
    except Exception:
        store.close(); raise
    return service


def attach_cw_simulation_routes(app, service: CwSimulationService | None):
    async def body(request: Request, keys: set[str]):
        # State-changing calls require an actual same-origin browser request.
        # No CORS, no credentials/principal/review inputs and no cross-site form path.
        if request.headers.get('origin') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'same-origin admission request required')
        if request.headers.get('content-type', '').split(';', 1)[0] != 'application/json':
            raise HTTPException(415, 'application/json required')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 32768: raise HTTPException(413, 'admission request exceeds 32 KiB')
        try:
            value = parse_json(bytes(raw))
            if not isinstance(value, dict) or set(value) != keys: raise ValueError('closed request shape required')
            return value
        except (ValueError, UnicodeError, RecursionError) as error:
            raise HTTPException(422, str(error)[:300]) from error

    def active():
        if service is None: raise HTTPException(503, 'no trusted simulation endpoint configured')
        return service

    @app.get('/api/cw-g01/profile')
    def profile():
        return service.describe() if service else dict(configured=False, physicalAcceptance=False,
            reason='No trusted simulation endpoint is configured. Offline rehearsal remains available.')

    @app.post('/api/cw-g01/admit')
    async def admit(request: Request):
        p = await body(request, {'requestId', 'candidate'})
        # The core service releases its lock while the existing PDP/verifier runs.
        from starlette.concurrency import run_in_threadpool
        try: return await run_in_threadpool(active().admit, p['requestId'], p['candidate'])
        except (ValueError, PermissionError, TypeError) as e: raise HTTPException(422, str(e)[:300]) from e

    @app.post('/api/cw-g01/{request_id}/start')
    async def start(request_id: str, request: Request):
        p = await body(request, {'executionToken', 'candidateDigest', 'binding', 'endpointId'})
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(active().start, request_id, p['executionToken'], candidate_digest=p['candidateDigest'],
                                          binding=p['binding'], endpoint_id=p['endpointId'])
        except KeyError as e: raise HTTPException(404, 'unknown attempt') from e
        except (ValueError, PermissionError, TypeError) as e: raise HTTPException(403, str(e)[:300]) from e

    @app.post('/api/cw-g01/{request_id}/cancel')
    async def cancel(request_id: str, request: Request):
        p = await body(request, {'revoke'})
        if type(p['revoke']) is not bool: raise HTTPException(422, 'boolean revoke flag required')
        try: return active().cancel(request_id, revoke=p['revoke'])
        except (ValueError, PermissionError) as e: raise HTTPException(403, str(e)[:300]) from e

    @app.get('/api/cw-g01/{request_id}/status')
    def status(request_id: str):
        try: return active().status(request_id)
        except KeyError as e: raise HTTPException(404, 'unknown attempt') from e

    @app.get('/api/cw-g01/{request_id}/capture')
    def capture(request_id: str):
        try: return active().capture(request_id)
        except KeyError as e: raise HTTPException(404, 'unknown attempt') from e
        except PermissionError as e: raise HTTPException(409, str(e)[:300]) from e

    @app.get('/api/cw-g02/{request_id}/evidence')
    def evidence(request_id: str):
        try:
            return Response(active().evidence_bundle(request_id), media_type='application/json', headers={
                'Content-Disposition': 'attachment; filename="attempt.cw-g02.bundle.json"', 'Cache-Control': 'no-store'})
        except KeyError as e: raise HTTPException(404, 'unknown attempt') from e
        except PermissionError as e: raise HTTPException(409, str(e)[:300]) from e
        except HTTPException: raise
        except Exception as e: raise HTTPException(503, 'simulation evidence sealing failed') from e

    @app.post('/api/cw-g02/{request_id}/verify')
    async def verify(request_id: str, request: Request):
        from .cw_evidence import MAX_BUNDLE_BYTES
        from starlette.concurrency import run_in_threadpool
        if request.headers.get('origin') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'same-origin evidence inspection required')
        if request.headers.get('content-type', '').split(';', 1)[0] != 'application/json':
            raise HTTPException(415, 'application/json required')
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk) > MAX_BUNDLE_BYTES:
                raise HTTPException(413, 'evidence bundle exceeds 2 MiB')
            raw.extend(chunk)
        if not raw: raise HTTPException(422, 'nonempty evidence bundle required')
        try:
            result = await run_in_threadpool(active().verify_evidence, request_id, bytes(raw))
            return Response(json.dumps(result, allow_nan=False), media_type='application/json', headers={'Cache-Control':'no-store'})
        except KeyError as e: raise HTTPException(404, 'unknown attempt; independently retained admission context is required') from e
        except PermissionError as e: raise HTTPException(409, str(e)[:300]) from e
        except (ValueError, RuntimeError) as e: raise HTTPException(503, 'evidence inspection unavailable; ask the service operator to inspect signing/configuration') from e
